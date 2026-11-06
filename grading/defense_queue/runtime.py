"""Подключение очереди к приложению; Sheets-клиент передаёт main.py."""
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from functools import lru_cache
import os
import json
import secrets
import threading
import time

from .policy import CandidateOrder, order_candidates, resolve_mode
from .storage import QueueStore
from .sync import course_timezone, sync_group

_LOCKS = {}
_LOCKS_GUARD = threading.Lock()
_CACHE = {}


@lru_cache(maxsize=8)
def _store(path):
    return QueueStore(path)


def queue_store():
    return _store(os.getenv('QUEUE_DB_PATH', 'data/queue.sqlite3'))


def sync_queue(course_id, group_id, course, *, fetch_grid, parse_deadline, force=False):
    if not course.get('queue', {}).get('enabled', False):
        raise ValueError('Очередь не включена для курса')
    store = queue_store()
    from .operations import effective_course
    course = effective_course(store, course_id, course)
    key = (str(store.path), course_id, group_id, json.dumps(course.get('queue', {}), sort_keys=True, default=str))
    with _LOCKS_GUARD:
        lock = _LOCKS.setdefault(key, threading.Lock())
    with lock:
        cached = _CACHE.get(key)
        if not force and cached and time.monotonic() - cached[0] < 15:
            return store, cached[1]
        # До чтения новых отметок сохраняется состав уже начавшихся занятий.
        now = int(time.time())
        with store.connection() as con:
            started = con.execute("SELECT session_id FROM sessions WHERE course_id=? AND group_id=? AND starts_at<=? AND enrollment_status!='cancelled'", (course_id, group_id, now)).fetchall()
            available = all(row[0] for row in con.execute("SELECT deadline_available FROM queue_candidates WHERE course_id=? AND group_id=? AND status='eligible'", (course_id, group_id)))
        for session in started:
            queue_view(store, course_id, group_id, course, deadlines_available=available, now=now, session_id=session[0])
        # Сеть вызывается вне транзакций SQLite.
        try:
            grid = fetch_grid()
        except Exception:
            if cached:
                return store, dict(cached[1], stale=True)
            raise
        result = sync_group(store, course_id, group_id, course, grid,
                            parse_deadline=parse_deadline, now=int(time.time()))
        _CACHE[key] = (time.monotonic(), result)
        return store, result


def queue_view(store, course_id, group_id, course, *, deadlines_available, now, session_id=None):
    from .operations import effective_course
    course = effective_course(store, course_id, course)
    with store.connection() as con:
        if session_id:
            session = con.execute('SELECT * FROM sessions WHERE session_id=? AND course_id=? AND group_id=?',
                                  (session_id, course_id, group_id)).fetchone()
        else:
            session = con.execute("""SELECT * FROM sessions WHERE course_id=? AND group_id=?
                AND starts_at>? AND enrollment_status NOT IN ('cancelled','closed')
                ORDER BY starts_at,session_id LIMIT 1""", (course_id, group_id, now)).fetchone()
    if session is not None and now >= session['starts_at']:
        with store.connection() as con:
            frozen = con.execute("SELECT details_json FROM queue_events WHERE session_id=? AND kind='roster_frozen' AND json_extract(details_json,'$.session.schedule_revision')=? ORDER BY event_id LIMIT 1", (session['session_id'], session['schedule_revision'])).fetchone()
        if frozen:
            result = json.loads(frozen[0])
            result['session'] = dict(session)
            return result
    mode = resolve_mode(deadlines_available=deadlines_available,
                        random_override=course.get('queue', {}).get('random', False))
    if session is None:
        with store.connection() as con:
            pending = con.execute('''SELECT c.candidate_id,c.lab_key,c.qualified_at,s.full_name,s.github_login
                FROM queue_candidates c JOIN students s USING(student_id)
                WHERE c.course_id=? AND c.group_id=? AND c.status='eligible'
                ORDER BY c.qualified_at,c.candidate_id''', (course_id, group_id)).fetchall()
        entries = [dict(candidate_id=row['candidate_id'], lab_key=row['lab_key'],
                        qualified_at=row['qualified_at'], full_name=row['full_name'], github=row['github_login'],
                        will_attend=False, answered=False, position=None, state='unconfirmed') for row in pending]
        return {'session': None, 'mode': mode.name, 'mode_locked': mode.locked,
                'entries': entries, 'attendance_open': False,
                'message': 'Ближайшее занятие ещё не назначено; порядок уточнится после назначения'}
    # Ключи создаются один раз, включая ещё не ответивших участников.
    with store.transaction() as con:
        candidates = con.execute("SELECT * FROM queue_candidates WHERE course_id=? AND group_id=? AND status='eligible' AND qualified_at<=?",
                                 (course_id, group_id, now if now < session['starts_at'] else session['starts_at'])).fetchall()
        for candidate in candidates:
            con.execute("""INSERT INTO session_participation(session_id,candidate_id,course_id,group_id,
                student_id,teacher_key,random_key,updated_at) VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(session_id,candidate_id) DO NOTHING""", (session['session_id'], candidate['candidate_id'],
                course_id, group_id, candidate['student_id'], session['teacher_key'], secrets.SystemRandom().random(), now))
        if now >= session['starts_at']:
            con.execute('UPDATE session_participation SET frozen_at=? WHERE session_id=? AND frozen_at IS NULL',
                        (session['starts_at'], session['session_id']))
    rows = store.roster(session['session_id'])
    if now >= session['starts_at']:
        rows = [row for row in rows if row['frozen_at'] is not None]
    zone = course_timezone(course)
    anchor = date.fromisoformat(course.get('queue', {}).get('semester_week_anchor', '1970-01-05'))
    candidates = [CandidateOrder(row['candidate_id'], row['qualified_at'],
                  datetime.fromtimestamp(row['deadline_at'], tz=timezone.utc) if row['deadline_at'] is not None else None,
                  row['random_key'], deadline_available=bool(row['deadline_available'])) for row in rows]
    ordered = order_candidates(candidates, mode=mode, session_start=datetime.fromtimestamp(session['starts_at'], tz=timezone.utc),
                               week_anchor=anchor, timezone=zone)
    by_id = {row['candidate_id']: row for row in rows}
    entries = []
    position = 0
    for candidate in ordered:
        row = by_id[candidate.candidate_id]
        if row['will_attend']:
            position += 1
        entries.append({'candidate_id': row['candidate_id'], 'full_name': row['full_name'],
                        'github': row['github_login'], 'lab_key': row['lab_key'],
                        'qualified_at': row['qualified_at'], 'priority': None if candidate.deadline is None else max(-1, (candidate.deadline.astimezone(ZoneInfo(zone)).date() - anchor).days // 7 - (datetime.fromtimestamp(session['starts_at'], ZoneInfo(zone)).date() - anchor).days // 7), 'will_attend': bool(row['will_attend']),
                        'answered': bool(row['attendance_answered']),
                        'position': position if row['will_attend'] else None,
                        'state': 'attending' if row['will_attend'] else 'declined' if row['attendance_answered'] else 'unconfirmed'})
    result = {'session': dict(session), 'mode': mode.name, 'mode_locked': mode.locked,
              'entries': entries, 'attendance_open': now < session['starts_at'] and session['enrollment_status'] not in ('closed', 'cancelled')}
    if now >= session['starts_at']:
        with store.transaction() as con:
            frozen = con.execute("SELECT details_json FROM queue_events WHERE session_id=? AND kind='roster_frozen' AND json_extract(details_json,'$.session.schedule_revision')=? ORDER BY event_id LIMIT 1", (session['session_id'], session['schedule_revision'])).fetchone()
            if frozen:
                return json.loads(frozen[0])
            con.execute("""INSERT INTO queue_events(session_id,actor_kind,actor_key,kind,details_json,occurred_at)
                VALUES (?,'system','queue','roster_frozen',?,?)""", (session['session_id'], json.dumps(result, ensure_ascii=False), now))
    return result
