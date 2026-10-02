"""Инлайн-кнопки и данные, которые в них зашиты."""
from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from subjects import SUBJECTS

ALL = "*"  # «все предметы» в кнопке показа очередей


class MenuCb(CallbackData, prefix="m"):
    action: str  # join | leave | queue | me | today | admin


class SubjCb(CallbackData, prefix="s"):
    action: str  # join | leave | queue | admin
    subject: str


class AdmCb(CallbackData, prefix="a"):
    action: str  # next | done | skip | refresh
    subject: str


def main_menu_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="📝 Записаться", callback_data=MenuCb(action="join"))
    b.button(text="🚪 Выйти из очереди", callback_data=MenuCb(action="leave"))
    b.button(text="📋 Очереди", callback_data=MenuCb(action="queue"))
    b.button(text="👤 Мои записи", callback_data=MenuCb(action="me"))
    b.button(text="🕒 Сегодня", callback_data=MenuCb(action="today"))
    b.button(text="🎓 Для старосты", callback_data=MenuCb(action="admin"))
    b.adjust(2, 2, 2)
    return b.as_markup()


def subjects_kb(action: str, with_all: bool = False) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for key, name in SUBJECTS.items():
        b.button(text=name, callback_data=SubjCb(action=action, subject=key))
    if with_all:
        b.button(text="Все очереди", callback_data=SubjCb(action=action, subject=ALL))
    b.adjust(2)
    return b.as_markup()


def queue_kb(subject: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🔄 Обновить", callback_data=SubjCb(action="queue", subject=subject))
    return b.as_markup()


def admin_kb(subject: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="▶️ Вызвать следующего", callback_data=AdmCb(action="next", subject=subject))
    b.button(text="✅ Сдал", callback_data=AdmCb(action="done", subject=subject))
    b.button(text="⏭ Не сдал", callback_data=AdmCb(action="skip", subject=subject))
    b.button(text="🔄 Обновить", callback_data=AdmCb(action="refresh", subject=subject))
    b.adjust(1, 2, 1)
    return b.as_markup()
