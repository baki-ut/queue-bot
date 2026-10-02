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
from common import ALLOWED_CHAT_ID, TOKEN, db, purge_finished

BOT_COMMANDS = [
    BotCommand(command="menu", description="Меню с кнопками"),
    BotCommand(command="queue", description="Все очереди"),
    BotCommand(command="me", description="Мои записи"),
    BotCommand(command="today", description="Пары сегодня и когда можно записаться"),
    BotCommand(command="cancel", description="Отменить запись"),
    BotCommand(command="help", description="Справка"),
]


PURGE_EVERY_SECONDS = 30


async def purge_loop() -> None:
    """Раз в полминуты убирать записи на закончившиеся пары."""
    while True:
        try:
            await purge_finished()
        except Exception:
            logging.exception("Не удалось очистить очереди")
        await asyncio.sleep(PURGE_EVERY_SECONDS)


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
    purger = asyncio.create_task(purge_loop())  # сразу же чистит то, что прошло, пока бот стоял
    try:
        await dp.start_polling(bot)
    finally:
        purger.cancel()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
