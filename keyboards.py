"""Inline keyboard buttons and main menu."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def btn_menu() -> InlineKeyboardButton:
    return InlineKeyboardButton("🏠 Меню", callback_data="go_menu")


def btn_cancel() -> InlineKeyboardButton:
    return InlineKeyboardButton("❌ Отмена", callback_data="go_menu")


def _pad(text: str, width: int = 28) -> str:
    """Дополнить строку справа до нужной ширины."""
    return text + "ㅤ" * max(0, width - len(text))


async def show_main_menu(bot, user_id: int, custom_text: str | None = None):
    from handlers.session import main_menu_messages, user_messages, cleanup_all_messages

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
            InlineKeyboardButton("⏰ Напоминания",  callback_data="open_reminders"),
            InlineKeyboardButton("⏱ Таймеры",      callback_data="open_timers"),
        ],
        [
            InlineKeyboardButton("💳 Карты",       callback_data="open_cards"),
            InlineKeyboardButton("📄 Документы",   callback_data="open_documents"),
        ],
        [
            InlineKeyboardButton("💰 Сумма",       callback_data="open_summa"),
            InlineKeyboardButton("🪙 Курс",       callback_data="open_rub"),
        ],
        [
            InlineKeyboardButton("📍 Локации",     callback_data="open_locations"),
            InlineKeyboardButton("🧹 Очистка",     callback_data="do_clean"),
        ],
    ]
    text = _pad(custom_text) if custom_text else header
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
            from handlers.session import logger
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
    except Exception as e:
        from handlers.session import logger
        logger.error(f"Не удалось показать меню: {e}")
