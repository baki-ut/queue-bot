"""Телеграм-бот очереди на сдачу практических работ."""
import asyncio
import logging
import os
from html import escape

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from dotenv import load_dotenv

from db import Database, Entry, JoinResult
from subjects import (
    NO_TOPIC, SUBJECTS, has_topics, join_example, parse_subject, subjects_hint, work_label,
)

load_dotenv()
TOKEN = os.environ["BOT_TOKEN"]
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x}
MAX_WORK = int(os.getenv("MAX_WORK", "10"))
MAX_TOPIC = int(os.getenv("MAX_TOPIC", "10"))

db = Database(os.getenv("DB_PATH", "queue.db"))
dp = Dispatcher()


# ---------- вспомогательное ----------

def mention(entry: Entry) -> str:
    return f'<a href="tg://user?id={entry.tg_id}">{escape(entry.full_name)}</a>'


def title(subject: str) -> str:
    return SUBJECTS[subject]


def label(e: Entry) -> str:
    return work_label(e.subject, e.topic, e.work_num)


def format_queue(subject: str, queue: list[Entry]) -> str:
    if not queue:
        return f"<b>{title(subject)}:</b> очередь пуста."
    lines = [f"<b>{title(subject)}:</b>"]
    for i, e in enumerate(queue, start=1):
        mark = " ← сдаёт" if e.called else ""
        lines.append(f"{i}. {escape(e.full_name)} — {label(e)}{mark}")
    return "\n".join(lines)


async def notify(bot: Bot, entry: Entry | None) -> None:
    """Личное сообщение. Работает, только если человек хоть раз писал боту в личку."""
    if entry is None:
        return
    try:
        await bot.send_message(
            entry.tg_id,
            f"Ваша очередь сдавать {title(entry.subject)}, {label(entry)}!",
        )
    except (TelegramForbiddenError, TelegramBadRequest):
        logging.info("Не удалось написать %s в личку", entry.tg_id)


def is_admin(message: Message) -> bool:
    return message.from_user is not None and message.from_user.id in ADMIN_IDS


async def remember_user(message: Message) -> None:
    await db.upsert_user(message.from_user.id, message.from_user.full_name)


async def subject_arg(message: Message, command: CommandObject) -> str | None:
    """Достать предмет из первого аргумента команды; если его нет — подсказать."""
    args = (command.args or "").split()
    subject = parse_subject(args[0]) if args else None
    if subject is None:
        await message.answer(
            f"Укажите предмет: {subjects_hint()}.\n"
            f"Например: /{command.command} рбд"
        )
    return subject


# ---------- команды для всех ----------

@dp.message(Command("start", "help"))
async def cmd_help(message: Message) -> None:
    await remember_user(message)
    await message.answer(
        "Бот очереди на сдачу практических работ.\n\n"
        f"<b>Предметы:</b> {subjects_hint()}\n\n"
        "/join предмет N — встать в очередь, например /join рбд 2\n"
        "/join мпс тема N — для МПС ещё и тема, например /join мпс 1 2\n"
        "/leave предмет — выйти из очереди по предмету\n"
        "/queue — все очереди, /queue рбд — одна\n"
        "/me — мои очереди и сданные работы\n\n"
        "<b>Для старосты:</b>\n"
        "/next предмет — вызвать следующего\n"
        "/done предмет — текущий сдал, вызвать следующего\n"
        "/skip предмет — текущий не сдал (убрать без зачёта)\n\n"
        "У каждого предмета своя очередь. Внутри неё раньше идёт тот, "
        "кто сдаёт более раннюю работу (у МПС — сначала по теме, потом по номеру).\n"
        "Чтобы получать уведомление «ваша очередь», напишите боту /start в личку."
    )


@dp.message(Command("id"))
async def cmd_id(message: Message) -> None:
    await message.answer(f"Ваш Telegram ID: <code>{message.from_user.id}</code>")


@dp.message(Command("join"))
async def cmd_join(message: Message, command: CommandObject) -> None:
    await remember_user(message)
    args = (command.args or "").split()
    subject = parse_subject(args[0]) if args else None
    if subject is None:
        await message.answer(
            "Формат: /join предмет номер, например /join рбд 2\n"
            "Для МПС ещё и тема: /join мпс 1 2 (тема 1, ПР 2)\n"
            f"Предметы: {subjects_hint()}"
        )
        return

    numbers = args[1:]
    need = 2 if has_topics(subject) else 1
    if len(numbers) != need or not all(n.isdigit() for n in numbers):
        await message.answer(f"Формат для {title(subject)}: {join_example(subject)}")
        return
    if has_topics(subject):
        topic, work_num = int(numbers[0]), int(numbers[1])
        if not 1 <= topic <= MAX_TOPIC:
            await message.answer(f"Номер темы — от 1 до {MAX_TOPIC}.")
            return
    else:
        topic, work_num = NO_TOPIC, int(numbers[0])
    if not 1 <= work_num <= MAX_WORK:
        await message.answer(f"Номер работы — от 1 до {MAX_WORK}.")
        return
    what = work_label(subject, topic, work_num)

    result = await db.join(message.from_user.id, subject, topic, work_num)
    if result is JoinResult.ALREADY_SUBMITTED:
        await message.answer(f"{title(subject)}, {what} у вас уже сдана.")
    elif result is JoinResult.ALREADY_IN_QUEUE:
        await message.answer(
            f"Вы уже в очереди по {title(subject)}. "
            f"Чтобы сменить работу: /leave {subject}, потом /join заново."
        )
    else:
        pos, _ = await db.position(message.from_user.id, subject)
        await message.answer(
            f"{escape(message.from_user.full_name)} записан(а): "
            f"{title(subject)}, {what}. Место в очереди: {pos}."
        )


@dp.message(Command("leave"))
async def cmd_leave(message: Message, command: CommandObject) -> None:
    subject = await subject_arg(message, command)
    if subject is None:
        return
    if await db.leave(message.from_user.id, subject):
        await message.answer(f"Вы вышли из очереди по {title(subject)}.")
    else:
        await message.answer(f"Вас нет в очереди по {title(subject)}.")


@dp.message(Command("queue"))
async def cmd_queue(message: Message, command: CommandObject) -> None:
    if command.args:
        subject = await subject_arg(message, command)
        if subject:
            await message.answer(format_queue(subject, await db.get_queue(subject)))
        return
    # без аргумента — все непустые очереди
    blocks = []
    for subject in SUBJECTS:
        queue = await db.get_queue(subject)
        if queue:
            blocks.append(format_queue(subject, queue))
    await message.answer("\n\n".join(blocks) if blocks else "Все очереди пусты.")


@dp.message(Command("me"))
async def cmd_me(message: Message) -> None:
    tg_id = message.from_user.id
    lines = ["<b>В очереди:</b>"]
    subjects_in_queue = await db.my_queues(tg_id)
    if subjects_in_queue:
        for subject in subjects_in_queue:
            pos, entry = await db.position(tg_id, subject)
            lines.append(f"• {title(subject)}, {label(entry)} — место {pos}")
    else:
        lines.append("нигде")

    lines.append("\n<b>Сдано:</b>")
    done = await db.submitted_works(tg_id)
    if done:
        for subject, works in done.items():
            name = SUBJECTS.get(subject, subject)
            lines.append(f"• {name}: " + ", ".join(work_label(subject, t, n) for t, n in works))
    else:
        lines.append("пока ничего")
    await message.answer("\n".join(lines))


@dp.message(Command("subjects"))
async def cmd_subjects(message: Message) -> None:
    await message.answer("Предметы: " + subjects_hint())


# ---------- команды старосты ----------

@dp.message(Command("next"))
async def cmd_next(message: Message, command: CommandObject) -> None:
    if not is_admin(message):
        await message.answer("Команда только для старосты.")
        return
    subject = await subject_arg(message, command)
    if subject is None:
        return
    current, called = await db.call_next(subject)
    if current:
        await message.answer(
            f"{title(subject)}: сейчас сдаёт {mention(current)}. "
            f"Завершите через /done {subject} или /skip {subject}."
        )
    elif called:
        await message.answer(
            f"{title(subject)}: сдаёт {mention(called)} — {label(called)}."
        )
        await notify(message.bot, called)
    else:
        await message.answer(f"{title(subject)}: очередь пуста.")


async def _finish(message: Message, command: CommandObject, submitted: bool) -> None:
    if not is_admin(message):
        await message.answer("Команда только для старосты.")
        return
    subject = await subject_arg(message, command)
    if subject is None:
        return
    finished, called = await db.finish_current(subject, submitted)
    if finished is None:
        await message.answer(
            f"{title(subject)}: сейчас никто не сдаёт. Вызовите через /next {subject}."
        )
        return
    verdict = "сдал(а)" if submitted else "убран(а) без зачёта"
    text = f"{title(subject)}: {escape(finished.full_name)} {verdict}, {label(finished)}."
    if called:
        text += f"\nСледующий: {mention(called)} — {label(called)}."
        await notify(message.bot, called)
    else:
        text += "\nОчередь пуста."
    await message.answer(text)


@dp.message(Command("done"))
async def cmd_done(message: Message, command: CommandObject) -> None:
    await _finish(message, command, submitted=True)


@dp.message(Command("skip"))
async def cmd_skip(message: Message, command: CommandObject) -> None:
    await _finish(message, command, submitted=False)


# ---------- запуск ----------

async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    await db.connect()
    bot = Bot(TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    try:
        await dp.start_polling(bot)
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
