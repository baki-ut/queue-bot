"""Настройки и общая логика, которой пользуются и команды, и кнопки."""
import logging
import os
from html import escape

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import User
from dotenv import load_dotenv

from db import Database, Entry, JoinResult
from schedule import block_label, can_join, is_expired, now_msk, queue_block
from subjects import SUBJECTS, work_label

# ---------- настройки из .env ----------

load_dotenv()
TOKEN = os.environ["BOT_TOKEN"]
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x}
MAX_WORK = int(os.getenv("MAX_WORK", "10"))
MAX_TOPIC = int(os.getenv("MAX_TOPIC", "10"))
_chat = os.getenv("ALLOWED_CHAT_ID", "").strip()
ALLOWED_CHAT_ID = int(_chat) if _chat else None
# 0 — отключить ограничения по расписанию (удобно для проверки бота ночью)
SCHEDULE_ENABLED = os.getenv("SCHEDULE_ENABLED", "1").strip() != "0"

db = Database(os.getenv("DB_PATH", "queue.db"))


# ---------- форматирование ----------

def title(subject: str) -> str:
    return SUBJECTS.get(subject, subject)


def label(e: Entry) -> str:
    return work_label(e.subject, e.topic, e.work_num)


def mention(entry: Entry) -> str:
    return f'<a href="tg://user?id={entry.tg_id}">{escape(entry.full_name)}</a>'


def user_link(user: User) -> str:
    """Упоминание пользователя: @username, если есть, иначе ссылка по ID."""
    if user.username:
        return f"@{user.username}"
    return f'<a href="tg://user?id={user.id}">{escape(user.full_name)}</a>'


def queue_header(subject: str) -> str:
    """«РБД (пара пн 05.10, 16:20):» — на какую практику эта очередь."""
    block = queue_block(subject)
    when = f" (пара {block_label(block)})" if block else ""
    return f"<b>{title(subject)}</b>{when}:"


def format_queue(subject: str, queue: list[Entry]) -> str:
    if not queue:
        return f"{queue_header(subject)} очередь пуста."
    lines = [queue_header(subject)]
    for i, e in enumerate(queue, start=1):
        mark = " ← сдаёт" if e.called else ""
        lines.append(f"{i}. {escape(e.full_name)} — {label(e)}{mark}")
    return "\n".join(lines)


async def queue_text(subject: str) -> str:
    return format_queue(subject, await db.get_queue(subject))


async def all_queues_text() -> str:
    blocks = []
    for subject in SUBJECTS:
        queue = await db.get_queue(subject)
        if queue:
            blocks.append(format_queue(subject, queue))
    return "\n\n".join(blocks) if blocks else "Все очереди пусты."


# ---------- пользователи и права ----------

def is_admin(user: User | None) -> bool:
    return user is not None and user.id in ADMIN_IDS


async def remember(user: User) -> None:
    await db.upsert_user(user.id, user.full_name)


async def notify(bot: Bot, entry: Entry | None) -> None:
    """Личное сообщение. Работает, только если человек хоть раз писал боту в личку."""
    if entry is None:
        return
    try:
        await bot.send_message(
            entry.tg_id, f"Ваша очередь сдавать {title(entry.subject)}, {label(entry)}!"
        )
    except (TelegramForbiddenError, TelegramBadRequest):
        logging.info("Не удалось написать %s в личку", entry.tg_id)


# ---------- действия ----------

def check_topic(topic: int) -> str | None:
    if not 1 <= topic <= MAX_TOPIC:
        return f"Номер темы — от 1 до {MAX_TOPIC}."
    return None


def join_closed(subject: str) -> str | None:
    """Причина, по которой сейчас нельзя записаться, или None."""
    return can_join(subject) if SCHEDULE_ENABLED else None


def check_work(work_num: int) -> str | None:
    if not 1 <= work_num <= MAX_WORK:
        return f"Номер работы — от 1 до {MAX_WORK}."
    return None


async def join_text(user: User, subject: str, topic: int, work_num: int) -> str:
    """Записать в очередь и вернуть ответ для пользователя. Номера уже проверены."""
    await remember(user)
    closed = join_closed(subject)  # время могло выйти, пока человек вводил номер
    if closed:
        return closed
    what = work_label(subject, topic, work_num)
    result = await db.join(user.id, subject, topic, work_num)
    if result is JoinResult.ALREADY_IN_QUEUE:
        return (
            f"Вы уже в очереди по {title(subject)}. "
            "Чтобы сменить работу, сначала выйдите из этой очереди."
        )
    pos, _ = await db.position(user.id, subject)
    block = queue_block(subject)
    if block is None:
        when = ""
    elif block.start <= now_msk():
        when = f" на текущую пару (до {block.end:%H:%M})"
    else:
        when = f" на пару {block_label(block)}"
    return (
        f"{escape(user.full_name)} записан(а){when}: {title(subject)}, {what}. "
        f"Место в очереди: {pos}."
    )


async def leave_text(user_id: int, subject: str) -> str:
    if await db.leave(user_id, subject):
        return f"Вы вышли из очереди по {title(subject)}."
    return f"Вас нет в очереди по {title(subject)}."


async def me_text(user_id: int) -> str:
    """Мои очереди — обычный текст без разметки."""
    lines = ["В очереди:"]
    subjects_in_queue = await db.my_queues(user_id)
    if subjects_in_queue:
        for subject in subjects_in_queue:
            pos, entry = await db.position(user_id, subject)
            lines.append(f"• {title(subject)}, {label(entry)} — место {pos}")
    else:
        lines.append("нигде")
    return "\n".join(lines)


async def next_action(bot: Bot, subject: str) -> tuple[str, Entry | None]:
    """Вызвать следующего. Возвращает (текст, кого вызвали или None)."""
    current, called = await db.call_next(subject)
    if current:
        return (
            f"{title(subject)}: сейчас сдаёт {mention(current)}. "
            "Сначала отметьте, сдал или нет.",
            None,
        )
    if called:
        await notify(bot, called)
        return f"{title(subject)}: сдаёт {mention(called)} — {label(called)}.", called
    return f"{title(subject)}: очередь пуста.", None


async def finish_action(bot: Bot, subject: str, submitted: bool) -> tuple[str, Entry | None]:
    """Отметить текущего и вызвать следующего. Возвращает (текст, кого вызвали)."""
    finished, called = await db.finish_current(subject)
    if finished is None:
        return f"{title(subject)}: сейчас никто не сдаёт. Сначала вызовите следующего.", None
    verdict = "сдал(а)" if submitted else "не сдал(а), убран(а) из очереди"
    text = f"{title(subject)}: {escape(finished.full_name)} {verdict}, {label(finished)}."
    if called:
        await notify(bot, called)
        text += f"\nСледующий: {mention(called)} — {label(called)}."
    else:
        text += "\nОчередь пуста."
    return text, called


async def purge_finished() -> None:
    """Очистить очереди на практики, которые уже закончились."""
    removed = await db.purge(is_expired)
    for subject, count in removed.items():
        logging.info("Практика по %s закончилась — убрано записей: %s", title(subject), count)
