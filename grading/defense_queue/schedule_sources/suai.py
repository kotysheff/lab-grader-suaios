"""Расписание ГУАП. HTML разбирается общим проверяемым парсером."""
from datetime import date
import re


def validate(config):
    if not re.fullmatch(r'[0-9]{1,20}', str(config.get('group_id', ''))):
        raise ValueError('Нужен числовой ID группы на сайте ГУАП')
    if not isinstance(config.get('subject'), str) or not config['subject'].strip():
        raise ValueError('Нужно точное название предмета')
    try:
        anchor = date.fromisoformat(config.get('week_anchor', ''))
    except (TypeError, ValueError):
        raise ValueError('Нужна дата начала нечётной недели') from None
    if anchor.weekday() != 0:
        raise ValueError('Начало первой нечётной недели должно быть понедельником')


def load(config, *, fetch, now, timezone):
    from ..schedule import parse_suai, expand_suai
    html = fetch(f'https://guap.ru/rasp/?gr={config["group_id"]}')
    return list(config.get('lessons', [])) + expand_suai(parse_suai(html), config, now=now, timezone=timezone)
