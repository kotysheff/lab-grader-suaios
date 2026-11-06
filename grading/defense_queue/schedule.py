"""Адаптер расписания ГУАП и импорт датированных занятий других вузов.

Формат ГУАП: https://github.com/markpolyak/suai-schedule-parser
Преобразование HTML повторяет структуру suai_rasp.parse; внешние процессы не запускаются.
Сеть передаётся как callback, поэтому импорт проверяется без сайта университета.
"""
from datetime import date, datetime, time, timedelta
from html.parser import HTMLParser
import hashlib
import re
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from .sync import course_timezone

DAYS = ('понедельник', 'вторник', 'среда', 'четверг', 'пятница', 'суббота', 'воскресенье')
SLOTS = (('09:30','11:00'), ('11:10','12:40'), ('13:00','14:30'), ('15:10','16:40'),
         ('17:00','18:30'), ('18:40','20:10'), ('20:20','21:50'))


class Node:
    def __init__(self, tag='', attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []

    @property
    def text(self):
        return ' '.join(' '.join(c.text if isinstance(c, Node) else c for c in self.children).split())

    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.walk()

    def has(self, *classes):
        return set(classes).issubset(self.attrs.get('class', '').split())


class Tree(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = Node(); self.stack = [self.root]
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs); self.stack[-1].children.append(node)
        if tag not in ('area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'):
            self.stack.append(node)

    def handle_endtag(self, tag):
        for i in range(len(self.stack)-1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]; break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def parse_suai(html):
    """Получить контракт Lesson из HTML страницы группы ГУАП."""
    root = Tree(html).root
    content = next((n for n in root.walk() if n.has('content')), None)
    if content is None:
        raise ValueError('ГУАП: не найден блок расписания; сохранённые занятия не изменены')
    day = slot = None
    lessons = []
    for node in content.walk():
        if node.tag == 'h4':
            label = node.text.lower()
            day = next((i for i, name in enumerate(DAYS) if name in label), None)
            slot = None
        if node.has('text-danger', 'mt-3'):
            match = re.search(r'(\d+)\s*пара', node.text)
            slot = int(match[1]) if match else None
        if not node.has('mb-3', 'py-2', 'd-flex', 'gap-2') or day is None or slot is None:
            continue
        descendants = list(node.walk())
        subject = next((n.text for n in descendants if n.has('lead')), '')
        kind = next((n.text for n in descendants if n.has('fs-6')), '')
        week = 1 if any(n.has('week1') for n in descendants) else 2 if any(n.has('week2') for n in descendants) else 0
        groups, teachers = [], []
        for n in descendants:
            if n.tag != 'a': continue
            query = parse_qs(urlparse(n.attrs.get('href', '')).query)
            for key, target in (('gr', groups), ('pr', teachers)):
                if key in query: target.append({'id': query[key][0], 'name': n.text})
        lessons.append(dict(day=day, slot=slot, week=week, subject=subject, kind=kind, groups=groups, teachers=teachers))
    return lessons


def validate_schedule(config):
    if not isinstance(config, dict): raise ValueError('Расписание должно быть объектом')
    if config.get('source', 'manual') not in ('manual', 'suai', 'import'):
        raise ValueError('Источник: manual, suai или import')
    if config.get('source') == 'suai':
        if not str(config.get('group_id', '')).isdigit(): raise ValueError('Нужен числовой ID группы на сайте ГУАП')
        if not config.get('subject', '').strip(): raise ValueError('Нужно точное название предмета')
        anchor = date.fromisoformat(config['week_anchor'])
        if anchor.weekday() != 0: raise ValueError('Начало первой нечётной недели должно быть понедельником')
    return config


def expand_suai(lessons, config, *, now, timezone):
    """Горизонт 8 недель. week_anchor — понедельник первой нечётной недели."""
    validate_schedule(dict(config, source='suai'))
    zone = ZoneInfo(timezone)
    first = datetime.fromtimestamp(now, zone).date()
    anchor = date.fromisoformat(config['week_anchor'])
    until = min(first + timedelta(days=56), date.fromisoformat(config.get('semester_end', '9999-12-31')))
    result = []
    for lesson in lessons:
        if lesson.get('subject', '').casefold() != config['subject'].strip().casefold(): continue
        if config.get('kind') and lesson.get('kind', '').casefold() != config['kind'].strip().casefold(): continue
        if config.get('teacher_id') and not any(str(t['id']) == str(config['teacher_id']) for t in lesson.get('teachers', [])): continue
        if lesson.get('groups') and not any(str(g['id']) == str(config['group_id']) for g in lesson['groups']): continue
        day = lesson['day']
        if isinstance(day, str): day = DAYS.index(day.lower())
        slot = int(lesson['slot'])
        if not 1 <= slot <= len(SLOTS): raise ValueError('Неизвестный номер пары ГУАП')
        current = first
        while current <= until:
            week = (current - anchor).days // 7 % 2 + 1
            if current.weekday() == day and lesson.get('week', 0) in (0, week):
                a, b = SLOTS[slot-1]
                start = datetime.combine(current, time.fromisoformat(a), zone)
                end = datetime.combine(current, time.fromisoformat(b), zone)
                if start.timestamp() > now:
                    result.append(dict(key=f'suai:{config["group_id"]}:{current}:{slot}', starts_at=int(start.timestamp()),
                                       ends_at=int(end.timestamp()), teacher_key=config.get('teacher_key', 'main'), source_kind='university'))
            current += timedelta(days=1)
    return result


def import_sessions(store, course_id, group_id, course, lessons, *, now):
    """Стабильные ключи; ручные переносы/отмены (revision>1) важнее обновления источника."""
    zone = course_timezone(course)
    prepared = []
    for lesson in lessons:
        start, end = lesson['starts_at'], lesson['ends_at']
        def stamp(value):
            if isinstance(value, (int, float)): return int(value)
            dt = datetime.fromisoformat(value)
            if dt.utcoffset() is None: raise ValueError('Даты импорта должны содержать часовой пояс')
            return int(dt.timestamp())
        start, end = stamp(start), stamp(end)
        if start >= end: raise ValueError('Окончание раньше начала')
        key = str(lesson['key'])
        sid = 'schedule-' + hashlib.sha256(f'{course_id}\n{group_id}\n{key}'.encode()).hexdigest()[:32]
        kind = lesson.get('source_kind', 'university')
        if kind not in ('university', 'manual', 'extra'): raise ValueError('Неизвестный тип занятия')
        prepared.append((sid, key, start, end, str(lesson.get('teacher_key', 'main')), kind))
    if len({r[1] for r in prepared}) != len(prepared): raise ValueError('Повторяющийся ключ занятия')
    store.configure_group(course_id, group_id, title=course.get('name', course_id), timezone=zone)
    with store.transaction() as con:
        for sid, key, start, end, teacher, kind in prepared:
            con.execute('''INSERT INTO sessions(session_id,course_id,group_id,teacher_key,source_key,source_kind,
                local_date,timezone,opens_at,starts_at,ends_at,expires_at,schedule_checked_at,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(course_id,group_id,source_key) DO UPDATE SET
                starts_at=excluded.starts_at,ends_at=excluded.ends_at,expires_at=excluded.expires_at,
                local_date=excluded.local_date,schedule_checked_at=excluded.schedule_checked_at
                WHERE sessions.schedule_revision=1 AND sessions.starts_at>? AND sessions.enrollment_status!='cancelled' ''',
                (sid,course_id,group_id,teacher,key,kind,datetime.fromtimestamp(start, ZoneInfo(zone)).date().isoformat(),
                 zone,min(now,start),start,end,end,now,now,now))
    return len(prepared)


def refresh_schedule(store, course_id, group_id, course, *, fetch, now):
    config = course.get('queue', {}).get('schedule', {}).get(group_id, {})
    validate_schedule(config)
    lessons = list(config.get('lessons', []))
    if config.get('source') == 'suai':
        html = fetch(f'https://guap.ru/rasp/?gr={config["group_id"]}')
        lessons += expand_suai(parse_suai(html), config, now=now, timezone=course_timezone(course))
    return import_sessions(store, course_id, group_id, course, lessons, now=now)
