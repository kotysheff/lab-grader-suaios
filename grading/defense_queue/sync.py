"""Синхронизация прочитанной таблицы: сетевой доступ и запись оценок отсутствуют."""
import re
from zoneinfo import ZoneInfo

from .sheet_state import first_admitted_lab, parse_lab_cell, read_deadline


def course_timezone(course):
    value = course.get('queue', {}).get('timezone', course.get('timezone', 'Europe/Moscow'))
    offset = re.fullmatch(r'UTC([+-])(\d{1,2})', value)
    if offset:
        value = f"Etc/GMT{'-' if offset[1] == '+' else '+'}{int(offset[2])}"
    ZoneInfo(value)
    return value


def sync_group(store, course_id, group_id, course, grid, *, parse_deadline, now):
    def cell(row, col):
        return grid[row - 1][col - 1].strip() if row <= len(grid) and col <= len(grid[row - 1]) else ''

    if len(grid) < 2 or 'GitHub' not in grid[0]:
        raise ValueError('В таблице отсутствует заголовок GitHub или строка лабораторных')
    labs = {str(key): value for key, value in course.get('labs', {}).items()}
    queue = course.get('queue', {})
    order = [str(key) for key in queue.get('required_labs', list(labs))]
    if not order or any(key not in labs for key in order) or len(set(order)) != len(order):
        raise ValueError('Некорректный порядок обязательных работ')
    columns = {}
    for key in order:
        label = labs[key].get('short-name')
        matches = [index + 1 for index, value in enumerate(grid[1]) if value == label]
        if len(matches) != 1:
            raise ValueError(f'Не найден однозначный столбец работы {key}')
        columns[key] = matches[0]
    github_col = grid[0].index('GitHub') + 1
    name_col = course.get('google', {}).get('student-name-column', 1) + 1
    students = []
    logins = set()
    for row in range(3, len(grid) + 1):
        name, login = cell(row, name_col), cell(row, github_col).lower()
        if not name or not login:
            continue
        if login in logins:
            raise ValueError('GitHub повторяется в таблице группы')
        logins.add(login)
        students.append((name, login, {key: cell(row, col) for key, col in columns.items()}))
    zone = course_timezone(course)
    deadlines = {}
    overrides = queue.get('deadlines', {})
    for key in order:
        if key in overrides:
            value = overrides[key]
            deadlines[key] = read_deadline('', parse=parse_deadline,
                                          manual=parse_deadline(str(value)) if value is not None else None,
                                          explicitly_no_deadline=value is None)
            if value is not None and deadlines[key].value is None:
                raise ValueError(f'Не удалось разобрать ручной срок работы {key}')
        else:
            deadlines[key] = read_deadline(cell(queue.get('deadline_row', 1), columns[key]), parse=parse_deadline)
    store.configure_group(course_id, group_id, title=course.get('name', course_id), timezone=zone)
    imported = 0
    for name, login, cells in students:
        student_id = store.student(name, login, now=now)
        with store.transaction() as con:
            for key, value in cells.items():
                if not parse_lab_cell(value).defended:
                    continue
                previous = con.execute("SELECT candidate_id FROM queue_candidates WHERE course_id=? AND student_id=? AND lab_key=? AND status='eligible'", (course_id, student_id, key)).fetchall()
                for candidate in previous:
                    con.execute("UPDATE queue_candidates SET status='defended' WHERE candidate_id=?", (candidate[0],))
                    store.event(con, candidate[0], 'sheet_defended', now)
            defended = frozenset(row[0] for row in con.execute("SELECT lab_key FROM queue_candidates WHERE course_id=? AND student_id=? AND status='defended'", (course_id, student_id)))
            key = first_admitted_lab(order, cells, defended_in_history=defended)
            old = con.execute("SELECT candidate_id,lab_key,group_id FROM queue_candidates WHERE course_id=? AND student_id=? AND status='eligible'", (course_id, student_id)).fetchone()
            if old and (old['lab_key'] != key or old['group_id'] != group_id):
                con.execute("UPDATE queue_candidates SET status='inactive' WHERE candidate_id=?", (old['candidate_id'],))
                store.event(con, old['candidate_id'], 'eligibility_changed', now)
        if key is not None:
            deadline = deadlines[key]
            store.qualify(course_id, group_id, student_id, key, order.index(key) + 1,
                          deadline_at=int(deadline.value.timestamp()) if deadline.value else None,
                          deadline_available=deadline.available, now=now)
            imported += 1
    return {'students': len(students), 'eligible': imported, 'deadlines_available': all(d.available for d in deadlines.values()),
            'deadlines': {key: {'available': d.available, 'value': int(d.value.timestamp()) if d.value else None} for key, d in deadlines.items()}}
