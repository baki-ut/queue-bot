"""Меню на кнопках.

Предмет выбирается кнопкой, а номер работы (и темы для МПС) человек
присылает отдельным сообщением — ответом на вопрос бота.
"""
from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, ForceReply, InlineKeyboardMarkup, Message

from common import (
    all_queues_text, check_topic, check_work, finish_action, is_admin, join_text,
    label, leave_text, me_text, mention, next_action, queue_text, remember, title, user_link,
)
from keyboards import (
    ALL, AdmCb, MenuCb, SubjCb, admin_kb, main_menu_kb, queue_kb, subjects_kb,
)
from subjects import NO_TOPIC, has_topics

router = Router()

ALERT_LIMIT = 200  # Telegram показывает во всплывающем окне не больше 200 символов


class JoinForm(StatesGroup):
    topic = State()  # ждём номер темы (только МПС)
    work = State()   # ждём номер ПР


def ask(text: str) -> ForceReply:
    """Поле ответа сразу открывается у того, кого спросили."""
    return ForceReply(selective=True, input_field_placeholder=text)


def is_answer(message: Message) -> bool:
    """В личке подходит любое сообщение, в группе — только ответ на вопрос бота.

    Так бот не путает обычную переписку в группе с ответом на свой вопрос.
    """
    if message.chat.type == ChatType.PRIVATE:
        return True
    reply = message.reply_to_message
    return reply is not None and reply.from_user is not None and reply.from_user.id == message.bot.id


async def edit(cb: CallbackQuery, text: str, kb: InlineKeyboardMarkup | None) -> None:
    """Обновить сообщение с кнопками; «ничего не изменилось» — не ошибка."""
    try:
        await cb.message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise


# ---------- главное меню ----------

@router.message(Command("menu"))
async def cmd_menu(message: Message) -> None:
    await remember(message.from_user)
    await message.answer("Что делаем?", reply_markup=main_menu_kb())


@router.callback_query(MenuCb.filter())
async def on_menu(cb: CallbackQuery, callback_data: MenuCb) -> None:
    action = callback_data.action
    if action == "join":
        await cb.message.answer("На какой предмет записываемся?", reply_markup=subjects_kb("join"))
    elif action == "leave":
        await cb.message.answer("Из какой очереди выйти?", reply_markup=subjects_kb("leave"))
    elif action == "queue":
        await cb.message.answer(
            "Какую очередь показать?", reply_markup=subjects_kb("queue", with_all=True)
        )
    elif action == "me":
        text = await me_text(cb.from_user.id)
        if len(text) <= ALERT_LIMIT:
            await cb.answer(text, show_alert=True)  # видно только нажавшему
            return
        await cb.message.answer(f"{user_link(cb.from_user)}\n{text}")
    elif action == "admin":
        if not is_admin(cb.from_user):
            await cb.answer("Это только для старосты.", show_alert=True)
            return
        await cb.message.answer("Какой предмет ведём?", reply_markup=subjects_kb("admin"))
    await cb.answer()


# ---------- выбор предмета ----------

@router.callback_query(SubjCb.filter())
async def on_subject(cb: CallbackQuery, callback_data: SubjCb, state: FSMContext) -> None:
    action, subject = callback_data.action, callback_data.subject

    if action == "join":
        await remember(cb.from_user)
        await state.update_data(subject=subject)
        if has_topics(subject):
            await state.set_state(JoinForm.topic)
            question = f"{user_link(cb.from_user)}, {title(subject)}: напишите номер темы."
        else:
            await state.set_state(JoinForm.work)
            question = f"{user_link(cb.from_user)}, {title(subject)}: напишите номер ПР."
        await cb.message.answer(question, reply_markup=ask("Например: 2"))
        await cb.answer()

    elif action == "leave":
        await cb.answer(await leave_text(cb.from_user.id, subject), show_alert=True)

    elif action == "queue":
        text = await all_queues_text() if subject == ALL else await queue_text(subject)
        await edit(cb, text, queue_kb(subject))
        await cb.answer("Обновлено")

    elif action == "admin":
        if not is_admin(cb.from_user):
            await cb.answer("Это только для старосты.", show_alert=True)
            return
        await edit(cb, await queue_text(subject), admin_kb(subject))
        await cb.answer()


# ---------- ввод номеров отдельным сообщением ----------

@router.message(Command("cancel"), StateFilter("*"))
@router.message(lambda m: (m.text or "").strip().lower() == "отмена", StateFilter("*"))
async def cancel(message: Message, state: FSMContext) -> None:
    if await state.get_state() is None:
        return
    await state.clear()
    await message.reply("Запись отменена.")


@router.message(JoinForm.topic, F.text, is_answer)
async def got_topic(message: Message, state: FSMContext) -> None:
    text = message.text.strip()
    if not text.isdigit():
        await message.reply("Нужно число — номер темы. Или «отмена».", reply_markup=ask("Номер темы"))
        return
    error = check_topic(int(text))
    if error:
        await message.reply(error, reply_markup=ask("Номер темы"))
        return
    await state.update_data(topic=int(text))
    await state.set_state(JoinForm.work)
    await message.reply("Теперь номер ПР.", reply_markup=ask("Например: 2"))


@router.message(JoinForm.work, F.text, is_answer)
async def got_work(message: Message, state: FSMContext) -> None:
    text = message.text.strip()
    if not text.isdigit():
        await message.reply("Нужно число — номер ПР. Или «отмена».", reply_markup=ask("Номер ПР"))
        return
    error = check_work(int(text))
    if error:
        await message.reply(error, reply_markup=ask("Номер ПР"))
        return
    data = await state.get_data()
    await state.clear()
    result = await join_text(
        message.from_user, data["subject"], data.get("topic", NO_TOPIC), int(text)
    )
    await message.reply(result)


# ---------- панель старосты ----------

@router.callback_query(AdmCb.filter())
async def on_admin(cb: CallbackQuery, callback_data: AdmCb) -> None:
    if not is_admin(cb.from_user):
        await cb.answer("Это только для старосты.", show_alert=True)
        return
    subject, action = callback_data.subject, callback_data.action

    result, called = "", None
    if action == "next":
        result, called = await next_action(cb.bot, subject)
    elif action in ("done", "skip"):
        result, called = await finish_action(cb.bot, subject, submitted=(action == "done"))

    panel = await queue_text(subject)
    await edit(cb, f"{result}\n\n{panel}" if result else panel, admin_kb(subject))
    if called:
        # отдельным сообщением, чтобы человека пингануло в группе
        await cb.message.answer(
            f"{mention(called)}, ваша очередь: {title(subject)}, {label(called)}!"
        )
    await cb.answer()
