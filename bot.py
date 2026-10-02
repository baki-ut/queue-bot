"""Телеграм-бот очереди на сдачу практических работ — точка входа."""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

import buttons
import commands
from access import GroupOnlyMiddleware
from common import ALLOWED_CHAT_ID, TOKEN, db

BOT_COMMANDS = [
    BotCommand(command="menu", description="Меню с кнопками"),
    BotCommand(command="queue", description="Все очереди"),
    BotCommand(command="me", description="Мои записи"),
    BotCommand(command="cancel", description="Отменить запись"),
    BotCommand(command="help", description="Справка"),
]


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    if ALLOWED_CHAT_ID is None:
        logging.warning("ALLOWED_CHAT_ID не задан — бот открыт для всех")

    dp = Dispatcher()
    access = GroupOnlyMiddleware(ALLOWED_CHAT_ID)
    dp.message.outer_middleware(access)
    dp.callback_query.outer_middleware(access)
    dp.include_routers(commands.router, buttons.router)

    await db.connect()
    bot = Bot(TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await bot.set_my_commands(BOT_COMMANDS)  # подсказки при вводе «/»
    try:
        await dp.start_polling(bot)
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
