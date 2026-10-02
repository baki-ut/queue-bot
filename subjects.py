"""Список предметов.

Ключ — как пишут в командах (/join рбд 2), значение — как показывать.
Чтобы добавить предмет, допишите строку сюда и перезапустите бота.
"""

SUBJECTS: dict[str, str] = {
    "мпс": "МПС",
    "оирткпс": "ОиРТКПС",
    "тестирование": "Тестирование",
    "рбд": "РБД",
    "котлин": "Котлин",
}

# Предметы, где работы разбиты по темам: /join мпс <тема> <ПР>
SUBJECTS_WITH_TOPICS: set[str] = {"мпс"}

NO_TOPIC = 0  # так хранится «темы нет» у остальных предметов


def parse_subject(text: str) -> str | None:
    """Вернуть ключ предмета или None, если такого нет."""
    key = text.strip().lower().replace("ё", "е")
    return key if key in SUBJECTS else None


def has_topics(subject: str) -> bool:
    return subject in SUBJECTS_WITH_TOPICS


def work_label(subject: str, topic: int, work_num: int) -> str:
    """«Тема 1, ПР 2» для предметов с темами, «ПР 2» для остальных."""
    if has_topics(subject):
        return f"Тема {topic}, ПР {work_num}"
    return f"ПР {work_num}"


def join_example(subject: str) -> str:
    return f"/join {subject} 1 2" if has_topics(subject) else f"/join {subject} 2"


def subjects_hint() -> str:
    return ", ".join(SUBJECTS)
