#!/usr/bin/env python3
"""Локальная очередь на публичных данных, без Google/GitHub-ключей и записи оценок."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
COURSE_ID, GROUP_ID = 'queue-live-os', '4434'
SPREADSHEET = '1mwFswSqBZHQjvfU7JtiT_f5yQMCCgjyGYrhjxLgBSus'
GID = '1544378737'


def local_directory(value):
    path = (ROOT / value).resolve()
    if not path.is_relative_to((ROOT / 'data').resolve()):
        raise ValueError('Данные локальной проверки должны находиться внутри data/ (он исключён из Git)')
    path.mkdir(parents=True, exist_ok=True)
    return path


def base_course():
    import yaml
    original = yaml.safe_load((ROOT / 'courses/operating-systems-2026.yaml').read_text())['course']
    course = deepcopy(original)
    course['name'] = 'ОС — локальная проверка публичных данных'
    course['queue'] = {
        'enabled': True, 'timezone': 'Europe/Moscow', 'registration_disabled': True,
        'semester_week_anchor': '2026-08-31',
        'sheet_source': {'type': 'public_csv', 'worksheets': {GROUP_ID: GID}},
        'schedule': {GROUP_ID: {
            'source': 'suai', 'university': 'ГУАП', 'group_id': '7116',
            'subject': 'Операционные системы', 'kind': 'Лабораторное занятие',
            'teacher_id': '39614', 'teacher_key': 'polyak', 'week_anchor': '2026-08-31',
        }},
    }
    course['google']['spreadsheet'] = SPREADSHEET
    return course


def select_sheet_labs(course, grid):
    """Локальный курс содержит только работы, присутствующие в предоставленном листе."""
    course = deepcopy(course)
    header = grid[1]
    course['labs'] = {key: lab for key, lab in course['labs'].items() if lab.get('short-name') in header}
    if not course['labs']:
        raise ValueError('Не найдены столбцы работ из конфигурации. Нужна проверка структуры листа')
    course['queue']['required_labs'] = list(course['labs'])
    return course


def allowed_path(path, method):
    public = f'/courses/{COURSE_ID}'
    student_queue = f'{public}/groups/{GROUP_ID}/queue'
    admin_queue = f'/admin/courses/{COURSE_ID}/groups/{GROUP_ID}/queue'
    settings = f'/admin/courses/{COURSE_ID}/queue/settings'
    queue_path = path == student_queue or path.startswith(student_queue + '/') or path == admin_queue or path.startswith(admin_queue + '/') or path == settings
    if method == 'OPTIONS':
        return True
    if method in ('GET', 'HEAD'):
        return queue_path or path in ('/courses', public, public+'/groups', public+f'/groups/{GROUP_ID}/labs',
                                      '/admin/check-auth', '/admin/queue/sessions', '/docs', '/openapi.json', '/redoc')
    return path == '/admin/login' or queue_path


def inspect_sources(course, *, fetch, now):
    from grading.defense_queue.public_sheet import read_public_grid
    from grading.defense_queue.schedule_sources.suai import load
    from grading.defense_queue.schedule import normalize_lessons
    grid = read_public_grid(course, GROUP_ID)
    course = select_sheet_labs(course, grid)
    source = course['queue']['schedule'][GROUP_ID]
    lessons = normalize_lessons(load(source, fetch=fetch, now=now, timezone=course['queue']['timezone']))
    if not lessons:
        raise ValueError('В расписании не найдены ближайшие лабораторные этого предмета и преподавателя. Проверьте фильтры источника')
    return course, grid, lessons


def prepare(args):
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    # Нельзя подхватить настоящий GitHub-токен или включить фоновые обращения до подготовки курса.
    os.environ.update(GITHUB_TOKEN='public-read-only', QUEUE_WORKER_ENABLED='0')
    import requests
    def fetch(url):
        response = requests.get(url, timeout=(5, 20))
        response.raise_for_status()
        response.encoding = 'utf-8'
        return response.text
    now = int(time.time())
    directory = local_directory(args.data_dir)
    try:
        course, grid, lessons = inspect_sources(base_course(), fetch=fetch, now=now)
        from grading.defense_queue.storage import QueueStore
        from grading.defense_queue.sync import sync_group, parse_queue_deadline
        from grading.sheets_client import parse_deadline
        # Диагностика не меняет предыдущую локальную историю и не сохраняет выгрузку студентов.
        with tempfile.TemporaryDirectory(dir=directory) as temp:
            summary = sync_group(QueueStore(Path(temp)/'check.sqlite3'), COURSE_ID, GROUP_ID, course, grid,
                                 parse_deadline=lambda value: parse_queue_deadline(value, course, parse_deadline), now=now)
        report = {'checked_at': datetime.fromtimestamp(now, timezone.utc).isoformat(), 'status': 'ok',
                  'group': GROUP_ID, 'students': summary['students'], 'eligible': summary['eligible'],
                  'labs': list(course['labs']), 'deadlines_available': summary['deadlines_available'],
                  'sessions': len(lessons), 'next_session': datetime.fromtimestamp(min(row['starts_at'] for row in lessons), timezone.utc).isoformat()}
    except Exception as error:
        # В отчёте нет ФИО, логинов, содержимого таблицы или секретов.
        report = {'checked_at': datetime.fromtimestamp(now, timezone.utc).isoformat(), 'status': 'error',
                  'error_type': type(error).__name__, 'message': str(error)[:800]}
        (directory/'last-check.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
        raise
    (directory/'last-check.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    return directory, course, lessons


def create_app(directory, course, lessons):
    configs = directory/'courses'
    configs.mkdir(exist_ok=True)
    (configs/'live.yaml').write_text(json.dumps({'course': course}, ensure_ascii=False), encoding='utf-8')
    (configs/'index.yaml').write_text(json.dumps({'version':'1.0','courses':[
        {'id':COURSE_ID,'file':'live.yaml','status':'active','priority':100}]}), encoding='utf-8')
    password = secrets.token_urlsafe(12)
    os.environ.update(ADMIN_LOGIN='local', ADMIN_PASSWORD=password, SECRET_KEY=secrets.token_hex(32),
                      QUEUE_DB_PATH=str(directory/'queue.sqlite3'), LOG_DIR=str(directory/'logs'))
    import main
    from fastapi.responses import JSONResponse
    from grading.defense_queue.runtime import queue_store
    from grading.defense_queue.schedule import import_sessions
    main.COURSES_DIR, main.INDEX_FILE = str(configs), str(configs/'index.yaml')
    import_sessions(queue_store(), COURSE_ID, GROUP_ID, course, lessons, now=int(time.time()))
    os.environ['QUEUE_WORKER_ENABLED'] = '1'

    @main.app.middleware('http')
    async def public_data_boundary(request, call_next):
        if not allowed_path(request.url.path, request.method):
            return JSONResponse(status_code=409, content={'detail': 'Локальная проверка: внешние источники доступны только для чтения. Регистрация, GitHub и запись оценок отключены.'})
        return await call_next(request)

    print('\nВнешние источники: только чтение. Действия очереди сохраняются только в локальной SQLite.', flush=True)
    print('Вход: http://localhost:5173/admin', flush=True)
    print(f'Логин: local; пароль: {password}', flush=True)
    print(f'Панель: http://localhost:5173/admin/courses/{COURSE_ID}/queue', flush=True)
    first = next(iter(course['labs']))
    print(f'Студент: http://localhost:5173/course/{COURSE_ID}/group/{GROUP_ID}/lab/{first}', flush=True)
    print(f'Данные и отчёт: {directory}\n', flush=True)
    return main.app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Проверить оба источника и структуру, сохранить обезличенный отчёт, без сервера')
    parser.add_argument('--data-dir', default='data/queue-live', help='Отдельный каталог внутри data/')
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    try:
        directory, course, lessons = prepare(args)
        if not args.check:
            import uvicorn
            uvicorn.run(create_app(directory, course, lessons), host='127.0.0.1', port=args.port)
    except Exception as error:
        print(f'Проверка не завершена: {type(error).__name__}: {error}', file=sys.stderr)
        print('Проверь интернет и доступ к публичному CSV/сайту ГУАП. Отчёт: data/queue-live/last-check.json (при другом --data-dir смотри указанный каталог).', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
