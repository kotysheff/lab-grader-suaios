"""Чтение публичного CSV Google Sheets без ключей и операций записи."""
import csv
import io
import re

import requests

MAX_BYTES = 4 * 1024 * 1024


def public_sheet_config(course):
    config = course.get('queue', {}).get('sheet_source')
    if config is None:
        return None
    if not isinstance(config, dict) or config.get('type') != 'public_csv':
        raise ValueError('queue.sheet_source: поддерживается type public_csv')
    spreadsheet = course.get('google', {}).get('spreadsheet')
    if not isinstance(spreadsheet, str) or not re.fullmatch(r'[A-Za-z0-9_-]{10,200}', spreadsheet):
        raise ValueError('Нужен корректный ID публичной Google-таблицы')
    sheets = config.get('worksheets')
    if not isinstance(sheets, dict) or not sheets:
        raise ValueError('Нужен словарь worksheets: группа → gid')
    for group, gid in sheets.items():
        if not isinstance(group, str) or not group.strip() or isinstance(gid, bool) or not re.fullmatch(r'[0-9]{1,20}', str(gid)):
            raise ValueError('worksheets: нужны строковые имена групп и числовые gid')
    return config


def parse_public_csv(content):
    if len(content) > MAX_BYTES:
        raise ValueError('Публичная таблица превышает допустимый размер')
    try:
        text = content.decode('utf-8-sig')
    except UnicodeDecodeError:
        raise ValueError('Экспорт таблицы должен использовать UTF-8') from None
    try:
        rows = list(csv.reader(io.StringIO(text, newline=''), strict=True))
    except csv.Error:
        raise ValueError('Не удалось разобрать CSV публичной таблицы') from None
    # Не принимать HTML входа Google или страницу ошибки как пустую таблицу.
    if len(rows) < 2 or sum(value.strip() == 'GitHub' for value in rows[0]) != 1:
        raise ValueError('Экспорт не содержит ожидаемые строки заголовков и GitHub. Проверьте публичный доступ и gid')
    if len(rows) > 10000 or any(len(row) > 1000 for row in rows):
        raise ValueError('Слишком большая таблица для очереди')
    return [[cell.strip() for cell in row] for row in rows]


def read_public_grid(course, group_id):
    config = public_sheet_config(course)
    if config is None or group_id not in config['worksheets']:
        raise ValueError('Для группы не задан публичный gid')
    spreadsheet = course['google']['spreadsheet']
    url = f'https://docs.google.com/spreadsheets/d/{spreadsheet}/export'
    # Путь фиксирован: произвольный URL/хост из конфигурации не запрашивается.
    with requests.get(url, params={'format': 'csv', 'gid': str(config['worksheets'][group_id])},
                      timeout=(5, 20), stream=True) as response:
        response.raise_for_status()
        content_type = response.headers.get('content-type', '').lower()
        if 'html' in content_type:
            raise ValueError('Вместо CSV Google вернул HTML. Проверьте доступ к таблице без входа')
        chunks, size = [], 0
        for chunk in response.iter_content(chunk_size=65536):
            size += len(chunk)
            if size > MAX_BYTES:
                raise ValueError('Публичная таблица превышает допустимый размер')
            chunks.append(chunk)
    return parse_public_csv(b''.join(chunks))
