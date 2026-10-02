"""Текстовые команды — запасной способ, если кнопки неудобны."""
from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from cleanup import MENU_TTL, answer_temp, forget
from common import (
    all_queues_text, check_topic, check_work, finish_action, is_admin, join_text,
    leave_text, me_text, next_action, queue_text, remember, title,
)
from keyboards import main_menu_kb
from schedule import today_text
from subjects import NO_TOPIC, has_topics, join_example, parse_subject, subjects_hint

router = Router()

HELP = (
    "Бот очереди на сдачу практических работ.\n\n"
    "Нажмите /menu — дальше всё кнопками.\n\n"
    "<b>То же самое командами:</b>\n"
    "/join предмет N — встать в очередь, например /join рбд 2\n"
    "/join мбп тема N — для МБП ещё и тема, например /join мбп 1 2\n"
    "/leave предмет — выйти из очереди\n"
    "/queue — все очереди, /queue рбд — одна\n"
    "/me — мои записи и места в очередях\n"
    "/today — пары сегодня и на что открыта запись\n"
    "/cancel — отменить начатую запись\n\n"
    "<b>Для старосты:</b> /next, /done, /skip + предмет\n\n"
    f"<b>Предметы:</b> {subjects_hint()}\n\n"
    "Раньше идёт тот, кто сдаёт более раннюю работу "
    "(у МБП — сначала по теме, потом по номеру).\n\n"
    "<b>Когда можно записаться</b> (время московское):\n"
    "• в день с парами — с начала первой пары −1 час до конца последней +1 час;\n"
    "• в день без пар — с 9:00 до 19:00;\n"
    "• очередь по предмету — на его ближайшую практику (или на идущую сейчас). "
    "Когда практика закончилась (сдвоенная — после второй пары), очередь очищается "
    "и начинается запись на следующую.\n\n"
    "Чтобы получать уведомление «ваша очередь», напишите боту /start в личку."
)


async def subject_arg(message: Message, command: CommandObject) -> str | None:
    """Достать предмет из первого аргумента команды; если его нет — подсказать."""
    args = (command.args or "").split()
    subject = parse_subject(args[0]) if args else None
    if subject is None:
        await answer_temp(message, 
            f"Укажите предмет: {subjects_hint()}.\nНапример: /{command.command} рбд"
        )
    return subject


@router.message(Command("start", "help"))
async def cmd_help(message: Message) -> None:
    await remember(message.from_user)
    sent = await message.answer(HELP, reply_markup=main_menu_kb())
    if message.chat.type != "private":  # в личке справку оставляем
        forget(message, sent, delay=MENU_TTL)


@router.message(Command("id"))
async def cmd_id(message: Message) -> None:
    await answer_temp(message, f"Ваш Telegram ID: <code>{message.from_user.id}</code>", delay=MENU_TTL)


@router.message(Command("chatid"))
async def cmd_chatid(message: Message) -> None:
    await answer_temp(message, f"ID этого чата: <code>{message.chat.id}</code>", delay=MENU_TTL)


@router.message(Command("join"))
async def cmd_join(message: Message, command: CommandObject) -> None:
    args = (command.args or "").split()
    subject = parse_subject(args[0]) if args else None
    if subject is None:
        await answer_temp(message, 
            "Формат: /join предмет номер, например /join рбд 2\n"
            "Для МБП ещё и тема: /join мбп 1 2 (тема 1, ПР 2)\n"
            f"Предметы: {subjects_hint()}\n\nИли нажмите /menu и выберите кнопками."
        )
        return

    numbers = args[1:]
    need = 2 if has_topics(subject) else 1
    if len(numbers) != need or not all(n.isdigit() for n in numbers):
        await answer_temp(message, f"Формат для {title(subject)}: {join_example(subject)}")
        return
    if has_topics(subject):
        topic, work_num = int(numbers[0]), int(numbers[1])
    else:
        topic, work_num = NO_TOPIC, int(numbers[0])

    error = (check_topic(topic) if has_topics(subject) else None) or check_work(work_num)
    if error:
        await answer_temp(message, error)
        return
    await answer_temp(message, await join_text(message.from_user, subject, topic, work_num))


@router.message(Command("leave"))
async def cmd_leave(message: Message, command: CommandObject) -> None:
    subject = await subject_arg(message, command)
    if subject:
        await answer_temp(message, await leave_text(message.from_user.id, subject))


@router.message(Command("queue"))
async def cmd_queue(message: Message, command: CommandObject) -> None:
    if command.args:
        subject = await subject_arg(message, command)
        if subject:
            await answer_temp(message, await queue_text(subject))
        return
    await answer_temp(message, await all_queues_text())


@router.message(Command("me"))
async def cmd_me(message: Message) -> None:
    await answer_temp(message, await me_text(message.from_user.id))


@router.message(Command("today"))
async def cmd_today(message: Message) -> None:
    await answer_temp(message, today_text())


@router.message(Command("subjects"))
async def cmd_subjects(message: Message) -> None:
    await answer_temp(message, "Предметы: " + subjects_hint())


# ---------- команды старосты ----------

@router.message(Command("next"))
async def cmd_next(message: Message, command: CommandObject) -> None:
    if not is_admin(message.from_user):
        await answer_temp(message, "Команда только для старосты.")
        return
    subject = await subject_arg(message, command)
    if subject:
        text, _ = await next_action(message.bot, subject)
        await message.answer(text)
        forget(message, delay=0)


async def _finish(message: Message, command: CommandObject, submitted: bool) -> None:
    if not is_admin(message.from_user):
        await answer_temp(message, "Команда только для старосты.")
        return
    subject = await subject_arg(message, command)
    if subject:
        text, _ = await finish_action(message.bot, subject, submitted)
        await message.answer(text)
        forget(message, delay=0)


@router.message(Command("done"))
async def cmd_done(message: Message, command: CommandObject) -> None:
    await _finish(message, command, submitted=True)


@router.message(Command("skip"))
async def cmd_skip(message: Message, command: CommandObject) -> None:
    await _finish(message, command, submitted=False)
