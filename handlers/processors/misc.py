"""Miscellaneous domain processors (summa, search, etc)."""
import logging

from telegram import InlineKeyboardMarkup

from db import db_set_summa
from keyboards import btn_cancel, show_main_menu
from handlers.session import register_message, start_process, finish_process, processes
from handlers.processors import register_message_handler, register_callback_handler
from utils import _pad

logger = logging.getLogger(__name__)


# ─── Summa ────────────────────────────────────────────────────────────────────

@register_message_handler("summa")
async def handle_summa_message(update, context, proc, state):
    from telegram import InlineKeyboardMarkup
    user = update.effective_user
    chat_id = update.effective_chat.id
    message = update.message or update.effective_message
    text = message.text.strip() if message.text else ""
    bot = context.bot
    register_message(user.id, chat_id, message.message_id)

    if state.get("step") == "waiting_summa":
        clean = text.replace(" ", "").replace(",", "")
        if not clean.isdigit():
            reply = await message.reply_text(
                "❌ Введи число (например: 500000):",
                reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
            )
            register_message(user.id, chat_id, reply.message_id)
            return

        summa_val = float(clean)
        await db_set_summa(user.id, summa_val)
        formatted = f"{int(summa_val):,}".replace(",", " ")
        await finish_process(bot, user.id, show_menu=False)
        await show_main_menu(bot, user.id, f"✅ Сумма сохранена: *{formatted}* сум")


# ─── Search ───────────────────────────────────────────────────────────────────

@register_message_handler("search")
async def handle_search_message(update, context, proc, state):
    user = update.effective_user
    chat_id = update.effective_chat.id
    message = update.message or update.effective_message
    text = message.text.strip() if message.text else ""
    bot = context.bot
    register_message(user.id, chat_id, message.message_id)

    if state.get("step") == "waiting_query":
        await finish_process(bot, user.id, show_menu=False)
        from ai import do_search
        await do_search(update, text, user.id, chat_id, bot)
        await show_main_menu(bot, user.id, "🔍 Что дальше?")


# ─── PIN Code ─────────────────────────────────────────────────────────────────

@register_message_handler("setpin")
async def handle_setpin_message(update, context, proc, state):
    """Обработка ввода PIN-кода для установки / смены."""
    from telegram import InlineKeyboardMarkup
    from db import db_set_pin, db_verify_pin
    from handlers.session import unlock_pin, is_pin_locked, record_pin_attempt

    user = update.effective_user
    chat_id = update.effective_chat.id
    message = update.message or update.effective_message
    text = message.text.strip() if message.text else ""
    bot = context.bot
    register_message(user.id, chat_id, message.message_id)

    step = state.get("step")

    if step == "waiting_old_pin":
        # Проверка блокировки
        if is_pin_locked(user.id):
            reply = await message.reply_text(
                _pad("⏳ Слишком много неверных попыток. Подожди минуту и попробуй снова."),
                reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
            )
            register_message(user.id, chat_id, reply.message_id)
            return

        # Проверяем старый PIN
        if not text.isdigit() or len(text) < 4:
            reply = await message.reply_text(
                _pad("❌ Введи текущий PIN (4+ цифр):"),
                reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
            )
            register_message(user.id, chat_id, reply.message_id)
            return

        if not await db_verify_pin(user.id, text):
            record_pin_attempt(user.id, False)
            if is_pin_locked(user.id):
                reply = await message.reply_text(
                    _pad("⏳ Слишком много неверных попыток. Подожди минуту и снова /setpin."),
                    reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
                )
            else:
                reply = await message.reply_text(
                    _pad("❌ Неверный PIN. Попробуй ещё или /cancel"),
                    reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
                )
            register_message(user.id, chat_id, reply.message_id)
            return

        # Старый PIN верный — сбрасываем счётчик
        record_pin_attempt(user.id, True)
        state["step"] = "waiting_new_pin"
        reply = await message.reply_text(
            _pad("🔐 Введи *новый* PIN-код (4 цифры):"),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        register_message(user.id, chat_id, reply.message_id)
        return

    if step == "waiting_pin":
        if not text.isdigit() or len(text) < 4:
            reply = await message.reply_text(
                _pad("❌ PIN должен содержать минимум 4 цифры. Попробуй ещё:"),
                reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
            )
            register_message(user.id, chat_id, reply.message_id)
            return

        state["pin"] = text
        state["step"] = "waiting_confirm"
        reply = await message.reply_text(
            _pad("🔐 Повтори PIN для подтверждения:"),
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        register_message(user.id, chat_id, reply.message_id)
        return

    if step == "waiting_new_pin":
        if not text.isdigit() or len(text) < 4:
            reply = await message.reply_text(
                _pad("❌ PIN должен содержать минимум 4 цифры. Попробуй ещё:"),
                reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
            )
            register_message(user.id, chat_id, reply.message_id)
            return

        state["pin"] = text
        state["step"] = "waiting_confirm_new"
        reply = await message.reply_text(
            _pad("🔐 Повтори *новый* PIN для подтверждения:"),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        register_message(user.id, chat_id, reply.message_id)
        return

    if step in ("waiting_confirm", "waiting_confirm_new"):
        if text != state.get("pin"):
            reply = await message.reply_text(
                _pad("❌ PIN не совпадает. Начни заново с /setpin"),
                reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
            )
            register_message(user.id, chat_id, reply.message_id)
            await finish_process(bot, user.id, show_menu=True)
            return

        pin = state["pin"]
        await db_set_pin(user.id, pin)
        unlock_pin(user.id)
        await finish_process(bot, user.id, show_menu=False)
        await show_main_menu(bot, user.id, "🔐 PIN-код установлен! Доступ к картам и файлам открыт.")
        return


@register_message_handler("enter_pin")
async def handle_enter_pin_message(update, context, proc, state):
    """Обработка ввода PIN для разблокировки карт/документов."""
    from telegram import InlineKeyboardMarkup
    from db import db_verify_pin
    from handlers.session import unlock_pin, is_pin_locked, record_pin_attempt

    user = update.effective_user
    chat_id = update.effective_chat.id
    message = update.message or update.effective_message
    text = message.text.strip() if message.text else ""
    bot = context.bot
    register_message(user.id, chat_id, message.message_id)

    step = state.get("step")
    return_to = state.get("return_to", "go_menu")

    if step == "waiting_pin":
        # Проверка блокировки
        if is_pin_locked(user.id):
            reply = await message.reply_text(
                _pad("⏳ Слишком много неверных попыток. Подожди минуту и попробуй снова."),
                reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
            )
            register_message(user.id, chat_id, reply.message_id)
            return

        if not text.isdigit() or len(text) < 4:
            reply = await message.reply_text(
                _pad("❌ PIN состоит из 4+ цифр. Попробуй ещё:"),
                reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
            )
            register_message(user.id, chat_id, reply.message_id)
            return

        if not await db_verify_pin(user.id, text):
            record_pin_attempt(user.id, False)
            if is_pin_locked(user.id):
                reply = await message.reply_text(
                    _pad("⏳ Слишком много неверных попыток. Подожди минуту и попробуй снова."),
                    reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
                )
                register_message(user.id, chat_id, reply.message_id)
            else:
                reply = await message.reply_text(
                    _pad("❌ Неверный PIN. Попробуй ещё или нажми Отмена."),
                    reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
                )
                register_message(user.id, chat_id, reply.message_id)
            return

        # PIN верный — сбрасываем счётчик попыток
        record_pin_attempt(user.id, True)
        unlock_pin(user.id)

        await finish_process(bot, user.id, show_menu=False)

        # Переходим сразу в запрошенный раздел
        if return_to == "open_cards":
            from handlers.processors.cards import _send_cards_content
            await _send_cards_content(bot, chat_id, user.id)
        elif return_to == "open_documents":
            from handlers.processors.documents import _send_documents_content
            await _send_documents_content(bot, chat_id, user.id)
        else:
            await show_main_menu(bot, user.id, "🔐 Доступ открыт!")


@register_message_handler("setpin_first")
async def handle_setpin_first_message(update, context, proc, state):
    """Обработка ввода PIN при первой установке (после нажатия Установить PIN)."""
    from telegram import InlineKeyboardMarkup
    from db import db_set_pin
    from handlers.session import unlock_pin

    user = update.effective_user
    chat_id = update.effective_chat.id
    message = update.message or update.effective_message
    text = message.text.strip() if message.text else ""
    bot = context.bot
    register_message(user.id, chat_id, message.message_id)

    step = state.get("step")
    return_to = state.get("return_to", "open_cards")

    if step == "waiting_pin":
        if not text.isdigit() or len(text) < 4:
            reply = await message.reply_text(
                _pad("❌ PIN должен содержать минимум 4 цифры:"),
                reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
            )
            register_message(user.id, chat_id, reply.message_id)
            return

        state["pin"] = text
        state["step"] = "waiting_confirm"
        reply = await message.reply_text(
            _pad("🔐 Повтори PIN для подтверждения:"),
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        register_message(user.id, chat_id, reply.message_id)
        return

    if step == "waiting_confirm":
        if text != state.get("pin"):
            reply = await message.reply_text(
                _pad("❌ PIN не совпадает. Попробуй ещё раз:"),
                reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
            )
            register_message(user.id, chat_id, reply.message_id)
            state["step"] = "waiting_pin"
            return

        pin = state["pin"]
        await db_set_pin(user.id, pin)
        unlock_pin(user.id)

        # Удаляем сообщение с PIN
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message.message_id)
        except Exception:
            pass

        await finish_process(bot, user.id, show_menu=False)
        await show_main_menu(bot, user.id, "🔐 PIN-код установлен! Доступ открыт.")


# ─── PIN Callbacks ────────────────────────────────────────────────────────────

@register_callback_handler("pin_setup_now")
async def cb_pin_setup_now(query, context, data, user, chat_id, bot):
    """Начать установку PIN-кода после нажатия кнопки Установить PIN."""
    proc = processes.get(user.id)
    return_to = "open_cards"
    if proc:
        return_to = proc.get("state", {}).get("return_to", "open_cards")

    start_process(user.id, chat_id, "setpin_first", {"step": "waiting_pin", "return_to": return_to}, query.message.message_id)
    await query.edit_message_text(
        _pad("🔐 *Установка PIN-кода*\n\nВведи PIN-код (4 цифры):"),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
    )


@register_callback_handler("lock_now")
async def cb_lock_now(query, context, data, user, chat_id, bot):
    """Заблокировать PIN-доступ и вернуться в меню."""
    from handlers.session import lock_pin
    lock_pin(user.id)
    from keyboards import show_main_menu
    await show_main_menu(bot, user.id, "🔒 Доступ к картам и файлам заблокирован.")

    # Удаляем сообщение, с которого нажали кнопку
    try:
        await bot.delete_message(chat_id=chat_id, message_id=query.message.message_id)
    except Exception:
        pass