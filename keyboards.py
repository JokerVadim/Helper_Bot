"""Inline keyboard buttons and main menu."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def btn_menu() -> InlineKeyboardButton:
    return InlineKeyboardButton("🏠 Меню", callback_data="go_menu")


def btn_cancel() -> InlineKeyboardButton:
    return InlineKeyboardButton("✖️ Отмена", callback_data="go_menu")


async def show_main_menu(bot, user_id: int, custom_text: str | None = None):
    from handlers.session import main_menu_messages

    keyboard = [
        [
            InlineKeyboardButton("📋 Списки",      callback_data="open_my_lists"),
            InlineKeyboardButton("➕ Добавить",    callback_data="newlist_personal"),
        ],
        [
            InlineKeyboardButton("⏰ Напоминания",  callback_data="open_reminders"),
            InlineKeyboardButton("➕ Добавить",    callback_data="add_reminder"),
        ],
        [
            InlineKeyboardButton("⏱ Таймеры",      callback_data="open_timers"),
            InlineKeyboardButton("➕ Добавить",    callback_data="add_timer"),
        ],
        [
            InlineKeyboardButton("💰 Сумма",        callback_data="open_summa"),
            InlineKeyboardButton("💱 Курс",         callback_data="open_rub"),
        ],
        [
            InlineKeyboardButton("🔍 Поиск",        callback_data="open_search"),
            InlineKeyboardButton("🧹 Очистка",      callback_data="do_clean"),
        ],
    ]
    text = custom_text or "👋 Привет! Выбери действие:"
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
