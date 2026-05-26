"""Inline keyboard buttons and main menu."""
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from utils import _pad

logger = logging.getLogger(__name__)


def btn_menu() -> InlineKeyboardButton:
    return InlineKeyboardButton("🏠 Меню", callback_data="go_menu")


def btn_cancel() -> InlineKeyboardButton:
    return InlineKeyboardButton("❌ Отмена", callback_data="go_menu")



async def show_main_menu(bot, user_id: int, custom_text: str | None = None):
    from handlers.session import main_menu_messages, user_messages, cleanup_all_messages
    from db import db_get_unread_errors_count
    from config import ADMIN_ID

    # Сначала удаляем ВСЕ предыдущие сообщения бота
    chat_id = user_id
    await cleanup_all_messages(bot, user_id, chat_id)

    header = _pad("Привет! Чем могу помочь:")

    keyboard = [
        [
            InlineKeyboardButton("📋 Списки",      callback_data="open_my_lists"),
            InlineKeyboardButton("📝 Заметки",      callback_data="open_notes"),
        ],
        [
            InlineKeyboardButton("💳 Карты",       callback_data="open_cards"),
            InlineKeyboardButton("📁 Файлы",       callback_data="open_documents"),
        ],
        [
            InlineKeyboardButton("⏰ Напоминания",  callback_data="open_reminders"),
            InlineKeyboardButton("⏱ Таймеры",      callback_data="open_timers"),
        ],
        [
            InlineKeyboardButton("📅 Календарь",    callback_data="open_calendar"),
            InlineKeyboardButton("📊 Сводка",       callback_data="open_summary"),
        ],
        [
            InlineKeyboardButton("💰 Сумма",       callback_data="open_summa"),
            InlineKeyboardButton("🏦 Курс",       callback_data="open_rub"),
        ],
        [
            InlineKeyboardButton("📍 Локации",     callback_data="open_locations"),
            InlineKeyboardButton("🌤 Погода",      callback_data="open_weather_menu"),
        ],
        [
            InlineKeyboardButton("🎂 Дни рождения", callback_data="open_birthdays"),
            InlineKeyboardButton("📦 Расходники",  callback_data="open_supplies"),
        ],
        [
            InlineKeyboardButton("🎮 Игры",        callback_data="open_games"),
            InlineKeyboardButton("🧹 Очистка",     callback_data="do_clean"),
        ],
    ]

    # ── Бейдж ошибок для админа ──
    if user_id == ADMIN_ID:
        unread = await db_get_unread_errors_count()
        if unread > 0:
            keyboard.append([
                InlineKeyboardButton(f"⚠️ Ошибки: {unread} непрочитанных", callback_data="admin_view_errors")
            ])
    text = _pad(custom_text) if custom_text is not None else header
    markup = InlineKeyboardMarkup(keyboard)
    old_menu_id = main_menu_messages.get(user_id)

    if old_menu_id:
        try:
            await bot.edit_message_text(
                chat_id=user_id,
                message_id=old_menu_id,
                text=text,
                parse_mode="Markdown",
                reply_markup=markup
            )
            return
        except Exception as e:
            logger.debug(f"Не удалось обновить старое меню {old_menu_id}: {e}")
            main_menu_messages.pop(user_id, None)

    try:
        msg = await bot.send_message(
            chat_id=user_id,
            text=text,
            parse_mode="Markdown",
            reply_markup=markup
        )
        main_menu_messages[user_id] = msg.message_id
        user_messages.setdefault(user_id, []).append(msg.message_id)
    except Exception as e:
        logger.error(f"Не удалось показать меню: {e}")
