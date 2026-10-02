"""Доступ только для своей группы.

Бот отвечает:
- в группе с ID из ALLOWED_CHAT_ID;
- в личке — только участникам этой группы.
В чужих группах бот молчит и пишет их ID в лог.
"""
import logging
import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message, TelegramObject

# Команды для первоначальной настройки работают везде.
SETUP_COMMANDS = ("/chatid", "/id")

MEMBER_STATUSES = {
    ChatMemberStatus.CREATOR,
    ChatMemberStatus.ADMINISTRATOR,
    ChatMemberStatus.MEMBER,
}


class GroupOnlyMiddleware(BaseMiddleware):
    def __init__(self, allowed_chat_id: int | None):
        self.allowed_chat_id = allowed_chat_id
        # Кэш проверок, чтобы не спрашивать Telegram на каждое сообщение:
        # user_id -> (состоит ли в группе, до какого времени верить ответу)
        self._cache: dict[int, tuple[bool, float]] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if self.allowed_chat_id is None:  # ограничение не настроено
            return await handler(event, data)

        if isinstance(event, CallbackQuery):  # нажатие на кнопку
            return await self._on_button(handler, event, data)

        parts = (event.text or "").split()
        command = parts[0].split("@")[0].lower() if parts else ""
        if command in SETUP_COMMANDS:
            return await handler(event, data)

        bot: Bot = data["bot"]
        chat = event.chat

        if chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
            if chat.id == self.allowed_chat_id:
                return await handler(event, data)
            # Из группы не выходим: при опечатке в ALLOWED_CHAT_ID бот иначе
            # покинул бы собственную группу. Просто молчим и пишем ID в лог.
            logging.warning(
                "Сообщение из группы %s (%s), а ALLOWED_CHAT_ID=%s — игнорирую",
                chat.id, chat.title, self.allowed_chat_id,
            )
            return None

        if chat.type == ChatType.PRIVATE and event.from_user:
            if await self._is_member(bot, event.from_user.id):
                return await handler(event, data)
            await event.answer("Бот доступен только участникам учебной группы.")
            return None

        return None  # каналы и прочее игнорируем

    async def _on_button(self, handler, event: CallbackQuery, data: dict[str, Any]) -> Any:
        if event.message is None:
            return None
        chat = event.message.chat
        if chat.id == self.allowed_chat_id:
            return await handler(event, data)
        if chat.type == ChatType.PRIVATE and await self._is_member(data["bot"], event.from_user.id):
            return await handler(event, data)
        await event.answer("Бот доступен только участникам учебной группы.", show_alert=True)
        return None

    async def _is_member(self, bot: Bot, user_id: int) -> bool:
        cached = self._cache.get(user_id)
        if cached and cached[1] > time.monotonic():
            return cached[0]
        try:
            member = await bot.get_chat_member(self.allowed_chat_id, user_id)
            ok = member.status in MEMBER_STATUSES or (
                member.status == ChatMemberStatus.RESTRICTED
                and getattr(member, "is_member", False)
            )
        except TelegramAPIError as e:
            logging.warning("Не удалось проверить участника %s: %s", user_id, e)
            ok = False
        # участников помним 10 минут, остальных — 1 минуту
        self._cache[user_id] = (ok, time.monotonic() + (600 if ok else 60))
        return ok
