"""Операции преподавателя. Авторизация выполняется HTTP-слоем."""
from datetime import date, datetime, timezone
import json
from uuid import uuid4

from .policy import priority_for
from .runtime import queue_view
from .storage import QueueClosed, QueueConflict
from .sync import course_timezone


def _event(con, session_id, kind, now, *, actor, entry_id=None, candidate_id=None, details=None):
    con.execute('''INSERT INTO queue_events(session_id,entry_id,candidate_id,actor_kind,actor_key,kind,details_json,occurred_at)
        VALUES (?,?,?,'teacher',?,?,?,?)''', (session_id, entry_id, candidate_id, actor, kind, json.dumps(details or {}, ensure_ascii=False), now))


def effective_course(store, course_id, course):
    result = dict(course, queue=dict(course.get('queue', {})))
    with store.connection() as con:
        settings = con.execute('SELECT * FROM queue_settings WHERE course_id=?', (course_id,)).fetchone()
    if settings:
        if settings['policy_override_set']:
            result['queue']['random'] = bool(settings['random_override'])
            result['queue']['deadlines'] = json.loads(settings['deadlines_json'])
        result['queue']['schedule'] = dict(result['queue'].get('schedule', {}), **json.loads(settings['schedule_json']))
    return result


def save_settings(store, course_id, *, random, deadlines, now):
    if type(random) is not bool or not isinstance(deadlines, dict):
        raise ValueError('Нужны режим очереди и словарь дедлайнов')
    with store.transaction() as con:
        con.execute('''INSERT INTO queue_settings(course_id,random_override,deadlines_json,updated_at,policy_override_set)
            VALUES (?,?,?,?,1) ON CONFLICT(course_id) DO UPDATE SET
            random_override=excluded.random_override,deadlines_json=excluded.deadlines_json,updated_at=excluded.updated_at,policy_override_set=1''',
            (course_id, int(random), json.dumps(deadlines), now))


def _insert_attempt(con, candidate, session, *, request_key, repeat, now, rank=None, snapshot=None):
    student = con.execute('SELECT * FROM students WHERE student_id=?', (candidate['student_id'],)).fetchone()
    cursor = con.execute('''INSERT INTO queue_entries(request_key,session_id,course_id,group_id,teacher_key,student_id,
        candidate_id,lab_key,lab_order,full_name_snapshot,github_snapshot,eligibility_snapshot,eligibility_checked_at,
        deadline_at,deadline_available,priority,is_repeat,joined_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,'admitted',?,?,?,?,?,?) ON CONFLICT(request_key) DO NOTHING''',
        (request_key, session['session_id'], session['course_id'], session['group_id'], session['teacher_key'],
         candidate['student_id'], candidate['candidate_id'], candidate['lab_key'], candidate['lab_order'],
         snapshot['full_name'] if snapshot else student['full_name'], snapshot['github'] if snapshot else student['github_login'], now, candidate['deadline_at'], candidate['deadline_available'], rank, int(repeat), now))
    return cursor.lastrowid


def materialize(store, view, course, *, now):
    session = view.get('session')
    if session is None or now < session['starts_at'] or session['enrollment_status'] == 'cancelled':
        return
    with store.transaction() as con:
        if con.execute('SELECT 1 FROM queue_reconciliations WHERE session_id=? AND done_at IS NOT NULL', (session['session_id'],)).fetchone():
            return
        for row in view['entries']:
            if not row['will_attend']:
                continue
            candidate = con.execute('SELECT * FROM queue_candidates WHERE candidate_id=?', (row['candidate_id'],)).fetchone()
            initial_key = f"initial:{session['session_id']}:{session['schedule_revision']}:{row['candidate_id']}"
            if con.execute("SELECT 1 FROM queue_entries WHERE candidate_id=? AND session_id=? AND (status!='expired' OR request_key=?)", (candidate['candidate_id'], session['session_id'], initial_key)).fetchone():
                continue
            if con.execute("SELECT 1 FROM queue_entries WHERE course_id=? AND student_id=? AND session_id!=? AND status IN ('waiting','called')", (session['course_id'], candidate['student_id'], session['session_id'])).fetchone():
                continue
            candidate = dict(candidate)
            for field in ('deadline_at','deadline_available'):
                if field in row: candidate[field] = row[field]
            rank = row.get('priority')
            if 'priority' not in row and candidate['deadline_at'] is not None and candidate['deadline_available']:
                rank = priority_for(datetime.fromtimestamp(candidate['deadline_at'], timezone.utc),
                                    datetime.fromtimestamp(session['starts_at'], timezone.utc),
                                    week_anchor=date.fromisoformat(course.get('queue', {}).get('semester_week_anchor', '1970-01-05')),
                                    timezone=course_timezone(course))
            _insert_attempt(con, candidate, session, request_key=initial_key, repeat=False, rank=rank, now=now, snapshot=row)
        con.execute('''INSERT INTO queue_reconciliations(session_id,due_at) VALUES (?,?)
            ON CONFLICT(session_id) DO NOTHING''',
            (session['session_id'], session['ends_at'] + 600))


def teacher_view(store, course_id, group_id, course, *, deadlines_available, now, session_id):
    view = queue_view(store, course_id, group_id, course, deadlines_available=deadlines_available, now=now, session_id=session_id)
    if view['session'] is None:
        raise ValueError('Занятие не найдено')
    materialize(store, view, course, now=now)
    with store.connection() as con:
        attempts = [dict(row) for row in con.execute('SELECT * FROM queue_entries WHERE session_id=? ORDER BY entry_id', (session_id,))]
        events = [dict(row) for row in con.execute('SELECT e.*,s.full_name,c.lab_key FROM queue_events e LEFT JOIN queue_candidates c USING(candidate_id) LEFT JOIN students s ON s.student_id=c.student_id WHERE e.session_id=? ORDER BY e.event_id DESC LIMIT 200', (session_id,))]
        sync = con.execute('SELECT * FROM queue_reconciliations WHERE session_id=?', (session_id,)).fetchone()
        available_candidates = [dict(row) for row in con.execute("""SELECT c.candidate_id,c.lab_key,s.full_name FROM queue_candidates c JOIN students s USING(student_id)
            WHERE c.course_id=? AND c.group_id=? AND c.status='eligible' AND NOT EXISTS
            (SELECT 1 FROM queue_entries e WHERE e.course_id=c.course_id AND e.student_id=c.student_id AND e.status IN ('waiting','called'))
            ORDER BY c.qualified_at,c.candidate_id""",(course_id,group_id))]
    latest = {row['candidate_id']: row for row in attempts}
    known = {row['candidate_id'] for row in view['entries']}
    entries = []
    for row in view['entries']:
        attempt = latest.get(row['candidate_id'])
        entries.append(dict(row, attempt=attempt))
    for cid, attempt in latest.items():
        if cid not in known:
            entries.append(dict(candidate_id=cid, full_name=attempt['full_name_snapshot'], github=attempt['github_snapshot'],
                                lab_key=attempt['lab_key'], qualified_at=attempt['joined_at'], will_attend=True, answered=True,
                                position=None, state='attending', attempt=attempt))
    active = sorted((row for row in attempts if row['status'] in ('waiting', 'called')),
                    key=lambda row: (row['is_repeat'], row['entry_id']))
    waiting = [row for row in active if row['status'] == 'waiting']
    called = next((row for row in active if row['status'] == 'called'), None)
    active_order = {row['candidate_id']: index for index, row in enumerate(active)}
    entries.sort(key=lambda row: (0, active_order[row['candidate_id']]) if row['candidate_id'] in active_order else (1, row['qualified_at']))
    return dict(view, entries=entries, attempts=attempts, history=events, available_candidates=available_candidates,
                current_entry_id=called['entry_id'] if called else None,
                next_entry_id=waiting[0]['entry_id'] if waiting else None,
                stats={status: sum(row['status'] == status for row in attempts)
                       for status in ('waiting', 'called', 'defended', 'failed', 'no_show', 'withdrawn', 'expired')},
                reconciliation=dict(sync) if sync else None)


def call_next(store, session_id, *, now, actor):
    with store.transaction() as con:
        session = con.execute('SELECT * FROM sessions WHERE session_id=?', (session_id,)).fetchone()
        if not session or now < session['starts_at'] or session['enrollment_status'] == 'cancelled':
            raise QueueClosed('Занятие ещё не началось или отменено')
        called = con.execute("SELECT * FROM queue_entries WHERE teacher_key=? AND status='called'", (session['teacher_key'],)).fetchone()
        if called:
            if called['session_id'] == session_id:
                return called['entry_id']
            raise QueueConflict('Преподаватель уже принимает студента другого занятия')
        row = con.execute("SELECT * FROM queue_entries WHERE session_id=? AND status='waiting' ORDER BY is_repeat,entry_id LIMIT 1", (session_id,)).fetchone()
        if not row:
            return None
        con.execute("UPDATE queue_entries SET status='called',called_at=?,version=version+1 WHERE entry_id=?", (now, row['entry_id']))
        _event(con, session_id, 'called', now, actor=actor, entry_id=row['entry_id'], candidate_id=row['candidate_id'])
        return row['entry_id']


def record_result(store, entry_id, outcome, *, now, actor):
    if outcome not in ('defended', 'failed', 'no_show'):
        raise ValueError('Неизвестный результат')
    with store.transaction() as con:
        row = con.execute('SELECT * FROM queue_entries WHERE entry_id=?', (entry_id,)).fetchone()
        if not row:
            raise ValueError('Попытка не найдена')
        if row['status'] == outcome:
            return
        if row['status'] != 'called':
            raise QueueConflict('Можно отметить только текущего вызванного студента')
        con.execute('UPDATE queue_entries SET status=?,closed_at=?,version=version+1 WHERE entry_id=?', (outcome, now, entry_id))
        _event(con, row['session_id'], outcome, now, actor=actor, entry_id=entry_id, candidate_id=row['candidate_id'])
        if outcome == 'defended':
            con.execute("UPDATE queue_candidates SET status='defended' WHERE candidate_id=?", (row['candidate_id'],))
        elif outcome == 'failed':
            session = con.execute('SELECT * FROM sessions WHERE session_id=?', (row['session_id'],)).fetchone()
            if now < session['ends_at']:
                candidate = con.execute('SELECT * FROM queue_candidates WHERE candidate_id=?', (row['candidate_id'],)).fetchone()
                _insert_attempt(con, candidate, session, request_key=f'retry:{entry_id}', repeat=True, now=now)


def add_to_tail(store, session_id, candidate_id, *, now, actor):
    with store.transaction() as con:
        candidate = con.execute("SELECT * FROM queue_candidates WHERE candidate_id=? AND status='eligible'", (candidate_id,)).fetchone()
        session = con.execute('SELECT * FROM sessions WHERE session_id=?', (session_id,)).fetchone()
        if candidate is None or session is None or (candidate['course_id'], candidate['group_id']) != (session['course_id'], session['group_id']):
            raise ValueError('Нужна допущенная работа своей группы')
        if session['enrollment_status'] == 'cancelled' or now >= session['ends_at']:
            raise QueueClosed('Занятие отменено или закончилось')
        old = con.execute("SELECT entry_id FROM queue_entries WHERE course_id=? AND student_id=? AND status IN ('waiting','called')", (candidate['course_id'], candidate['student_id'])).fetchone()
        if old:
            raise QueueConflict('У студента уже есть активная попытка')
        entry_id = _insert_attempt(con, candidate, session, request_key=f'manual:{session_id}:{candidate_id}:{uuid4().hex}', repeat=True, now=now)
        _event(con, session_id, 'added_to_tail', now, actor=actor, entry_id=entry_id, candidate_id=candidate_id)
        return entry_id


def withdraw(store, entry_id, *, now, actor):
    with store.transaction() as con:
        row = con.execute('SELECT * FROM queue_entries WHERE entry_id=?', (entry_id,)).fetchone()
        if not row:
            raise ValueError('Попытка не найдена')
        if row['status'] == 'withdrawn':
            return
        if row['status'] not in ('waiting', 'called'):
            raise QueueConflict('Попытка уже завершена')
        con.execute("UPDATE queue_entries SET status='withdrawn',closed_at=?,version=version+1 WHERE entry_id=?", (now, entry_id))
        _event(con, row['session_id'], 'withdrawn', now, actor=actor, entry_id=entry_id, candidate_id=row['candidate_id'])


def move_session(store, session_id, *, starts_at, ends_at, local_date, now, actor):
    if starts_at >= ends_at:
        raise ValueError('Окончание должно быть позже начала')
    with store.transaction() as con:
        session = con.execute('SELECT * FROM sessions WHERE session_id=?', (session_id,)).fetchone()
        if session is None:
            raise ValueError('Занятие не найдено')
        if con.execute("SELECT 1 FROM queue_entries WHERE session_id=? AND status IN ('called','defended','failed','no_show')", (session_id,)).fetchone():
            raise QueueConflict('Приём уже начат: создайте дополнительное занятие вместо переноса истории')
        con.execute('''UPDATE sessions SET opens_at=?,starts_at=?,ends_at=?,expires_at=?,local_date=?,
            enrollment_status='scheduled',schedule_revision=schedule_revision+1 WHERE session_id=?''',
            (min(now, starts_at), starts_at, ends_at, ends_at, local_date, session_id))
        con.execute("UPDATE queue_entries SET status='expired',closed_at=? WHERE session_id=? AND status='waiting'", (now, session_id))
        con.execute('UPDATE session_participation SET frozen_at=NULL WHERE session_id=?', (session_id,))
        # Старый снимок остаётся в истории; новое занятие использует новую ревизию.
        _event(con, session_id, 'schedule_changed', now, actor=actor,
               details={'old_start': session['starts_at'], 'starts_at': starts_at, 'ends_at': ends_at})
        con.execute('UPDATE queue_reconciliations SET due_at=?,done_at=NULL,claimed_at=NULL WHERE session_id=?', (ends_at + 600, session_id))


def cancel_session(store, session_id, *, now, actor):
    with store.transaction() as con:
        if con.execute('SELECT 1 FROM sessions WHERE session_id=?', (session_id,)).fetchone() is None:
            raise ValueError('Занятие не найдено')
        con.execute("UPDATE sessions SET enrollment_status='cancelled',schedule_revision=schedule_revision+1 WHERE session_id=?", (session_id,))
        con.execute("UPDATE queue_entries SET status='expired',closed_at=? WHERE session_id=? AND status IN ('waiting','called')", (now, session_id))
        _event(con, session_id, 'cancelled', now, actor=actor)


def save_schedule(store, course_id, group_id, config, *, now):
    from .schedule import validate_schedule
    validate_schedule(config)
    with store.transaction() as con:
        row = con.execute('SELECT schedule_json FROM queue_settings WHERE course_id=?', (course_id,)).fetchone()
        configs = json.loads(row[0]) if row else {}
        configs[group_id] = config
        con.execute("INSERT INTO queue_settings(course_id,schedule_json,updated_at) VALUES (?,?,?) ON CONFLICT(course_id) DO UPDATE SET schedule_json=excluded.schedule_json,updated_at=excluded.updated_at", (course_id, json.dumps(configs, ensure_ascii=False), now))


def set_enrollment(store, session_id, *, closed, now, actor):
    with store.transaction() as con:
        session = con.execute('SELECT * FROM sessions WHERE session_id=?', (session_id,)).fetchone()
        if not session or session['enrollment_status'] == 'cancelled' or now >= session['starts_at']:
            raise QueueClosed('Посещение можно менять только до начала неотменённого занятия')
        con.execute('UPDATE sessions SET enrollment_status=? WHERE session_id=?', ('closed' if closed else 'scheduled',session_id))
        _event(con,session_id,'enrollment_closed' if closed else 'enrollment_opened',now,actor=actor)


def promote_next_labs(store, session_id, *, now, actor):
    """Повтор синхронизации после сетевого сбоя не теряет следующую защиту."""
    with store.transaction() as con:
        session=con.execute('SELECT * FROM sessions WHERE session_id=?',(session_id,)).fetchone()
        if not session or not session['starts_at'] <= now < session['ends_at'] or session['enrollment_status']=='cancelled':
            return
        candidates=con.execute("""SELECT DISTINCT c.candidate_id FROM queue_candidates c
            JOIN queue_entries old ON old.student_id=c.student_id AND old.course_id=c.course_id
            WHERE old.session_id=? AND old.status='defended' AND c.status='eligible'
            AND c.group_id=? AND c.lab_order>old.lab_order
            AND NOT EXISTS(SELECT 1 FROM queue_entries e WHERE e.session_id=? AND e.candidate_id=c.candidate_id)
            AND NOT EXISTS(SELECT 1 FROM queue_entries e WHERE e.course_id=c.course_id AND e.student_id=c.student_id AND e.status IN ('waiting','called'))
            ORDER BY c.candidate_id""",(session_id,session['group_id'],session_id)).fetchall()
        for row in candidates:
            add_to_tail(store,session_id,row['candidate_id'],now=now,actor=actor)
