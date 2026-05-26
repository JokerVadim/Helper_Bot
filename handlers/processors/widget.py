"""Widget settings module — настройка времени отправки сводки дня.

Упрощённый UI: бот показывает текущее время и просит ввести новое в формате ЧЧ:ММ.
"""
import logging
import re

from telegram import InlineKeyboardMarkup

from db import db_get_widget_settings, db_set_widget_time
from handlers.processors import register_message_handler, register_callback_handler
from handlers.session import register_message, start_process, finish_process
from keyboards import btn_cancel, show_main_menu
from utils import _pad

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Callback Handlers
# ═══════════════════════════════════════════════════════════════════════════════


@register_callback_handler("widget_settings")
async def cb_widget_settings(query, context, data, user, chat_id, bot):
    """Открыть настройки виджета — показать текущее время + попросить ввести новое."""
    settings = await db_get_widget_settings( user.id)
    current_time = settings.get("time", "08:00") if settings else "08:00"

    text = _pad(
        f"📅 *Сводка дня (Виджет)*\n\n"
        f"⏰ Текущее время отправки: `{current_time}`\n\n"
        f"Введи новое время в формате *ЧЧ:ММ*\n"
        f"Например: `07:30` или `18:00`"
    )

    start_process(user.id, chat_id, "widget_time", {
        "step": "waiting_time",
    }, query.message.message_id)

    await query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Message Handlers
# ═══════════════════════════════════════════════════════════════════════════════


@register_message_handler("widget_time")
async def handle_widget_time(update, context, proc, state):
    """Обработка ввода времени виджета."""
    user = update.effective_user
    chat_id = update.effective_chat.id
    message = update.message or update.effective_message
    text = message.text.strip() if message.text else ""
    bot = context.bot
    register_message(user.id, chat_id, message.message_id)

    if not re.match(r"^([01]\d|2[0-3]):([0-5]\d)$", text):
        reply = await message.reply_text(
            _pad("❌ Неверный формат. Введи время в формате *ЧЧ:ММ*\n\n"
                 "Например: `07:30`, `14:00`, `23:15`"),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        register_message(user.id, chat_id, reply.message_id)
        return

    await db_set_widget_time( user.id, text)
    await finish_process(bot, user.id, show_menu=False)

    await show_main_menu(bot, user.id, _pad(f"✅ Время отправки сводки установлено на *{text}*!"))
