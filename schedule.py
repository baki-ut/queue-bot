"""Расписание группы и правила, когда можно записываться в очередь.

Правила:
1. В день с парами записываться можно с начала первой пары минус 1 час
   до конца последней пары плюс 1 час.
2. В день без пар — с 9:00 до 19:00.
3. Очередь по предмету — на его ближайшую практику. Если практика идёт сейчас,
   запись идёт на неё. Когда практика кончилась (сдвоенная — после второй пары),
   очередь очищается и начинается запись на следующую. Лекции не считаются.

Время московское. Расписание правится в EVERY_WEEK, ODD_WEEK и EVEN_WEEK.
"""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

LOOKAHEAD_DAYS = 21  # насколько вперёд искать следующую практику

from subjects import SUBJECTS

# В Москве нет перехода на летнее время, поэтому хватает фиксированного UTC+3.
MSK = timezone(timedelta(hours=3), "MSK")

# Понедельник 1-й недели семестра. Нечётные недели: 1, 3, 5...
SEMESTER_START = date(2026, 8, 31)

MARGIN = timedelta(hours=1)               # «± 1 час» вокруг учебного дня
FREE_DAY_OPEN = (time(9, 0), time(19, 0))  # окно записи в день без пар

PAIRS = {
    1: (time(9, 0), time(10, 30)),
    2: (time(10, 40), time(12, 10)),
    3: (time(12, 40), time(14, 10)),
    4: (time(14, 20), time(15, 50)),
    5: (time(16, 20), time(17, 50)),
    6: (time(18, 0), time(19, 30)),
}

LK, PR = "ЛК", "ПР"
MON, TUE, WED, THU, FRI, SAT, SUN = range(7)

# День недели → [(номер пары, предмет, тип)]

EVERY_WEEK = {  # одинаково каждую неделю
    MON: [
        (3, "котлин", PR),
        (4, "котлин", PR),
        (5, "рбд", PR),
        (6, "рбд", PR),
    ],
}

ODD_WEEK = {  # нечётные недели: 1, 3, 5...
    FRI: [
        (1, "оирткпс", LK),
        (2, "котлин", LK),
        (3, "мбп", PR),
        (4, "мбп", PR),
        (5, "оирткпс", PR),
    ],
}

EVEN_WEEK = {  # чётные недели: 2, 4, 6...
    FRI: [
        (1, "мбп", LK),
        (2, "котлин", LK),
        (3, "мбп", PR),
        (4, "мбп", PR),
        (5, "оирткпс", PR),
    ],
    SAT: [
        (1, "тестирование", LK),
        (2, "рбд", LK),
        (3, "тестирование", PR),
        (4, "тестирование", PR),
    ],
}


@dataclass
class Lesson:
    number: int
    subject: str
    kind: str
    start: datetime
    end: datetime


def now_msk() -> datetime:
    return datetime.now(MSK)


def week_number(d: date) -> int:
    return (d - SEMESTER_START).days // 7 + 1


def lessons_on(d: date) -> list[Lesson]:
    by_parity = EVEN_WEEK if week_number(d) % 2 == 0 else ODD_WEEK
    items = EVERY_WEEK.get(d.weekday(), []) + by_parity.get(d.weekday(), [])
    return [
        Lesson(
            n, subject, kind,
            datetime.combine(d, PAIRS[n][0], MSK),
            datetime.combine(d, PAIRS[n][1], MSK),
        )
        for n, subject, kind in sorted(items)
    ]


def _name(subject: str) -> str:
    return SUBJECTS.get(subject, subject)


@dataclass
class Block:
    """Практика по предмету подряд идущими парами (сдвоенная пара — один блок)."""
    subject: str
    start: datetime
    end: datetime


def practice_blocks(d: date) -> list[Block]:
    blocks: list[Block] = []
    last_number = None
    for l in lessons_on(d):
        if l.kind != PR:
            last_number = None
            continue
        if blocks and blocks[-1].subject == l.subject and last_number == l.number - 1:
            blocks[-1].end = l.end          # продолжение сдвоенной пары
        else:
            blocks.append(Block(l.subject, l.start, l.end))
        last_number = l.number
    return blocks


def queue_block(subject: str, now: datetime | None = None) -> Block | None:
    """Практика, на которую сейчас идёт запись: идущая сейчас или ближайшая следующая."""
    now = now or now_msk()
    day = now.date()
    for offset in range(LOOKAHEAD_DAYS):
        for b in practice_blocks(day + timedelta(days=offset)):
            if b.subject == subject and b.end > now:
                return b
    return None


def is_expired(subject: str, joined_at: datetime, now: datetime | None = None) -> bool:
    """Закончилась ли практика, на которую человек записался в момент joined_at."""
    block = queue_block(subject, joined_at.astimezone(MSK))
    return block is not None and block.end <= (now or now_msk())


def can_join(subject: str, now: datetime | None = None) -> str | None:
    """None — записаться можно, иначе текст с причиной отказа."""
    now = now or now_msk()
    lessons = lessons_on(now.date())

    if not lessons:
        start, end = FREE_DAY_OPEN
        if start <= now.time() < end:
            return None
        return f"Сегодня пар нет — записываться можно с {start:%H:%M} до {end:%H:%M}."

    window_from = lessons[0].start - MARGIN
    window_to = lessons[-1].end + MARGIN
    if not window_from <= now <= window_to:
        return (
            f"Сегодня записываться можно с {window_from:%H:%M} до {window_to:%H:%M} "
            "(учебное время ± 1 час)."
        )
    return None


WEEKDAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


def block_label(block: Block, now: datetime | None = None) -> str:
    """«идёт сейчас, до 15:50» или «пн 05.10, 12:40»."""
    now = now or now_msk()
    if block.start <= now:
        return f"идёт сейчас, до {block.end:%H:%M}"
    return f"{WEEKDAYS[block.start.weekday()]} {block.start:%d.%m}, {block.start:%H:%M}"


def today_text(now: datetime | None = None) -> str:
    """Короткая сводка: какие сегодня пары и на что открыта запись."""
    now = now or now_msk()
    week = week_number(now.date())
    parity = "чётная" if week % 2 == 0 else "нечётная"
    lessons = lessons_on(now.date())
    lines = [f"Сегодня {now:%d.%m}, {week} неделя ({parity}), сейчас {now:%H:%M} МСК."]

    if not lessons:
        start, end = FREE_DAY_OPEN
        lines.append(f"Пар нет. Запись на любой предмет с {start:%H:%M} до {end:%H:%M}.")
        return "\n".join(lines)

    lines.append("Пары:")
    for l in lessons:
        lines.append(f"{l.number}. {l.start:%H:%M}–{l.end:%H:%M} {_name(l.subject)} ({l.kind})")
    window_from = lessons[0].start - MARGIN
    window_to = lessons[-1].end + MARGIN
    if not window_from <= now <= window_to:
        lines.append(f"Запись открыта с {window_from:%H:%M} до {window_to:%H:%M}.")
    else:
        lines.append("Сейчас запись открыта на все предметы.")
    return "\n".join(lines)
