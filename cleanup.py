"""Автоудаление сообщений, чтобы бот не засорял чат.

- Промежуточные сообщения процесса (выбор предмета, вопросы бота, ответы
  с номерами) удаляются сразу после того, как запись завершена или отменена.
- Итоговый ответ бота и команда пользователя — через CLEANUP_DELAY секунд.
- Меню и списки, которыми не воспользовались, — через MENU_TTL секунд.

Сообщения пользователей в группе бот может удалять, только если он админ
с правом «Удаление сообщений». Без этого права удаляются только его собственные.
Таймеры живут в памяти: если бота перезапустить, ранее запланированные
удаления не выполнятся (сообщения просто останутся).
"""
import asyncio
import logging
import os

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message
from dotenv import load_dotenv

load_dotenv()  # настройки ниже читаются из .env

AUTODELETE = os.getenv("AUTODELETE", "1").strip() != "0"
CLEANUP_DELAY = int(os.getenv("CLEANUP_DELAY", "60"))
MENU_TTL = int(os.getenv("MENU_TTL", "300"))

_tasks: set[asyncio.Task] = set()  # держим ссылки, чтобы задачи не собрал сборщик мусора


def delete_later(bot: Bot, chat_id: int, message_ids, delay: int) -> None:
    """Удалить сообщения через delay секунд (0 — сразу, в фоне)."""
    ids = [m for m in message_ids if m]
    if not AUTODELETE or not ids:
        return

    async def job() -> None:
        if delay > 0:
            await asyncio.sleep(delay)
        for message_id in ids:
            try:
                await bot.delete_message(chat_id, message_id)
            except TelegramAPIError as e:  # уже удалено, нет прав, старше 48 часов
                logging.debug("Не удалось удалить %s: %s", message_id, e)

    task = asyncio.create_task(job())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def forget(*messages: Message | None, delay: int) -> None:
    """То же для объектов сообщений (все из одного чата)."""
    messages = [m for m in messages if m is not None]
    if messages:
        delete_later(messages[0].bot, messages[0].chat.id, [m.message_id for m in messages], delay)


async def answer_temp(message: Message, text: str, delay: int = CLEANUP_DELAY, **kwargs) -> Message:
    """Ответить и удалить через delay и ответ, и сообщение пользователя."""
    sent = await message.answer(text, **kwargs)
    forget(message, sent, delay=delay)
    return sent
