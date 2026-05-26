"""Cards domain processor."""
import asyncio
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from db import (
    db_get_cards, db_save_card, db_card_exists, db_update_card,
)
from keyboards import btn_menu, btn_cancel, show_main_menu
from handlers.session import register_message, finish_process, processes
from handlers.processors import register_message_handler, register_callback_handler
from utils import md, _pad

logger = logging.getLogger(__name__)

# ─── Action Mode ──────────────────────────────────────────────────────────────
_card_action_modes: dict[int, str] = {}

def _get_card_action_mode(user_id: int) -> str:
    return _card_action_modes.get(user_id, "")

def _set_card_action_mode(user_id: int, mode: str):
    if mode:
        _card_action_modes[user_id] = mode
    else:
        _card_action_modes.pop(user_id, None)


# ─── Card Preview ───────────────────────────────────────────────────────────
_card_preview: dict[int, dict | None] = {}  # user_id -> {name, number} or None
_card_preview_task: dict[int, asyncio.Task | None] = {}

def _set_card_preview(user_id: int, card: dict | None):
    if card is not None:
        _card_preview[user_id] = {"name": card["name"], "number": card["number"]}
    else:
        _card_preview.pop(user_id, None)


async def _auto_hide_preview(user_id: int, chat_id: int, message_id: int, bot):
    """Скрыть превью карты через 5 секунд."""
    await asyncio.sleep(5)
    if user_id in _card_preview:
        _card_preview.pop(user_id, None)
        _card_preview_task[user_id] = None
        text, keyboard = await _build_cards_content(user_id)
        try:
            await bot.edit_message_text(
                _pad(text), parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard),
                chat_id=chat_id, message_id=message_id
            )
        except Exception:
            pass


# ─── Message Handlers ────────────────────────────────────────────────────────

@register_message_handler("card")
async def handle_card_message(update, context, proc, state):
    from telegram import InlineKeyboardMarkup
    user = update.effective_user
    chat_id = update.effective_chat.id
    message = update.message or update.effective_message
    text = message.text.strip() if message.text else ""
    bot = context.bot
    register_message(user.id, chat_id, message.message_id)

    step = state.get("step")

    if step == "waiting_name":
        if await db_card_exists(user.id, text):
            reply = await message.reply_text(
                _pad("⚠️ Карта с таким названием уже есть!"),
                reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
            )
            register_message(user.id, chat_id, reply.message_id)
            return

        state["name"] = text
        state["step"] = "waiting_number"
        reply = await message.reply_text(
            _pad(f"💳 Название: *{md(text)}*\n\nТеперь введи номер карты (только цифры):"),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        register_message(user.id, chat_id, reply.message_id)
        return

    if step == "waiting_number":
        clean = text.replace(" ", "").replace("-", "")
        if not clean.isdigit() or len(clean) < 13 or len(clean) > 19:
            reply = await message.reply_text(
                _pad("❌ Введи номер карты (13-19 цифр):"),
                reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
            )
            register_message(user.id, chat_id, reply.message_id)
            return

        name = state.get("name", "Карта")
        await db_save_card(user.id, name, clean)
        await finish_process(bot, user.id, show_menu=False)
        await show_main_menu(bot, user.id, f"✅ Карта *{md(name)}* сохранена!")


@register_message_handler("card_edit")
async def handle_card_edit_message(update, context, proc, state):
    from telegram import InlineKeyboardMarkup
    user = update.effective_user
    chat_id = update.effective_chat.id
    message = update.message or update.effective_message
    text = message.text.strip() if message.text else ""
    bot = context.bot
    register_message(user.id, chat_id, message.message_id)

    step = state.get("step")
    card_id = state.get("card_id")

    if step == "waiting_name":
        if await db_card_exists(user.id, text):
            reply = await message.reply_text(
                _pad("⚠️ Карта с таким названием уже есть!"),
                reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
            )
            register_message(user.id, chat_id, reply.message_id)
            return
        state["name"] = text
        state["step"] = "waiting_number"
        reply = await message.reply_text(
            _pad(f"💳 Новое название: *{md(text)}*\n\nТеперь введи новый номер карты (только цифры):"),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        register_message(user.id, chat_id, reply.message_id)
        return

    if step == "waiting_number":
        clean = text.replace(" ", "").replace("-", "")
        if not clean.isdigit() or len(clean) < 13 or len(clean) > 19:
            reply = await message.reply_text(
                _pad("❌ Введи номер карты (13-19 цифр):"),
                reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
            )
            register_message(user.id, chat_id, reply.message_id)
            return
        name = state.get("name", "Карта")
        await db_update_card(user.id, card_id, name, clean)
        await finish_process(bot, user.id, show_menu=False)
        await show_main_menu(bot, user.id, f"✅ Карта *{md(name)}* обновлена!")


@register_message_handler("card_edit_name")
async def handle_card_edit_name_message(update, context, proc, state):
    user = update.effective_user
    chat_id = update.effective_chat.id
    message = update.message or update.effective_message
    text = message.text.strip() if message.text else ""
    bot = context.bot
    register_message(user.id, chat_id, message.message_id)

    card_id = state.get("card_id")

    if await db_card_exists(user.id, text):
        reply = await message.reply_text(
            _pad("⚠️ Карта с таким названием уже есть!"),
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        register_message(user.id, chat_id, reply.message_id)
        return

    cards = await db_get_cards(user.id)
    card = next((c for c in cards if c["id"] == card_id), None)
    if card:
        await db_update_card(user.id, card_id, text, card["number"])
    await finish_process(bot, user.id, show_menu=False)
    await _send_cards_content(bot, chat_id, user.id, f"✅ Название изменено: {md(text)}")


@register_message_handler("card_edit_number")
async def handle_card_edit_number_message(update, context, proc, state):
    user = update.effective_user
    chat_id = update.effective_chat.id
    message = update.message or update.effective_message
    text = message.text.strip() if message.text else ""
    bot = context.bot
    register_message(user.id, chat_id, message.message_id)

    card_id = state.get("card_id")

    clean = text.replace(" ", "").replace("-", "")
    if not clean.isdigit() or len(clean) < 13 or len(clean) > 19:
        reply = await message.reply_text(
            _pad("❌ Введи номер карты (13-19 цифр):"),
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        register_message(user.id, chat_id, reply.message_id)
        return

    cards = await db_get_cards(user.id)
    card = next((c for c in cards if c["id"] == card_id), None)
    if card:
        await db_update_card(user.id, card_id, card["name"], clean)
    await finish_process(bot, user.id, show_menu=False)
    await _send_cards_content(bot, chat_id, user.id, "✅ Номер карты обновлён!")


# ─── Callback Handlers ───────────────────────────────────────────────────────

async def _show_cards(query, custom_text: str = None):
    """Показать список карт."""
    user = query.from_user
    from handlers.session import is_pin_unlocked
    from db import db_has_pin
    chat_id = query.message.chat_id
    bot = query.message.get_bot()

    has_pin = await db_has_pin(user.id)

    if has_pin and not is_pin_unlocked(user.id):
        # PIN установлен — просим ввести
        from handlers.session import start_process
        start_process(user.id, chat_id, "enter_pin", {"step": "waiting_pin", "return_to": "open_cards"}, query.message.message_id)
        await query.edit_message_text(
            _pad("🔐 *Введите PIN-код*\n\nДоступ к картам защищён PIN-кодом."),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Отмена", callback_data="go_menu")]
            ])
        )
        return

    if not has_pin:
        # PIN не установлен — предложим установить в первый раз
        from handlers.session import start_process
        start_process(user.id, chat_id, "setpin_first", {"step": "waiting_choice", "return_to": "open_cards"}, query.message.message_id)
        await query.edit_message_text(
            _pad("🔐 *Защита данных*\n\nЭтот раздел содержит чувствительные данные.\n\nУстановить PIN-код для защиты?"),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Установить PIN", callback_data="pin_setup_now")],
                [InlineKeyboardButton("⏭ Пропустить", callback_data="open_cards_unlocked")],
                [InlineKeyboardButton("❌ Отмена", callback_data="go_menu")],
            ])
        )
        return

    await _show_cards_content(query, custom_text)


async def _build_cards_content(user_id: int, custom_text: str = None) -> tuple[str, list]:
    """Построить текст и клавиатуру списка карт."""
    cards = await db_get_cards(user_id)
    action_mode = _get_card_action_mode(user_id)

    keyboard = []
    preview = _card_preview.get(user_id)
    for card in cards:
        is_active = preview and preview["name"] == card["name"] and preview["number"] == card["number"]
        if action_mode == "delete":
            btn = InlineKeyboardButton(f"🗑 {card['name']}", callback_data=f"delcard_{card['id']}")
        elif action_mode == "edit_name":
            btn = InlineKeyboardButton(f"✏️ {card['name']}", callback_data=f"editcardname_{card['id']}")
        elif action_mode == "edit_number":
            btn = InlineKeyboardButton(f"✏️ {card['name']}", callback_data=f"editcardnum_{card['id']}")
        else:
            prefix = "👁 " if is_active else ""
            btn = InlineKeyboardButton(f"{prefix}{card['name']}", callback_data=f"showcard_{card['id']}")
        keyboard.append([btn])

    LINE_W = 32
    if preview:
        number = preview["number"]
        formatted = " ".join([number[i:i+4] for i in range(0, len(number), 4)])
        name_display = md(preview['name'])
        pad = max(1, LINE_W - len(f"💳 {preview['name']}"))
        text = f"💳 *{name_display}*" + "\u3164" * pad + "\n`" + f"{formatted}`"
    else:
        pad = max(1, LINE_W - len("💳 Твои карты:"))
        text = "💳 *Твои карты:*" + "\u3164" * pad
    if action_mode:
        _labels = {"delete": "🗑 Удалить", "edit_name": "✏️ Название", "edit_number": "✏️ Номер"}
        text += f"\n\n*Режим:* ✅ {_labels.get(action_mode, action_mode)}"
    if custom_text:
        text = custom_text
    if not cards:
        text = "💳 *Карты* — пока нет сохранённых карт."

    delete_lbl = "✅ 🗑 Удалить" if action_mode == "delete" else "🗑 Удалить"
    name_lbl = "✅ ✏️ Название" if action_mode == "edit_name" else "✏️ Название"
    num_lbl = "✅ ✏️ Номер" if action_mode == "edit_number" else "✏️ Номер"
    keyboard.append([
        InlineKeyboardButton("✚ Добавить", callback_data="add_card"),
        InlineKeyboardButton(delete_lbl, callback_data="cardstogglemode_delete"),
    ])
    keyboard.append([
        InlineKeyboardButton(name_lbl, callback_data="cardstogglemode_edit_name"),
        InlineKeyboardButton(num_lbl, callback_data="cardstogglemode_edit_number"),
    ])
    keyboard.append([InlineKeyboardButton("🔒 Закрыть", callback_data="lock_now"), btn_menu()])
    return text, keyboard


async def _show_cards_content(query, custom_text: str = None):
    """Показать список карт без PIN-проверки (редактирует текущее сообщение)."""
    text, keyboard = await _build_cards_content(query.from_user.id, custom_text)
    await query.edit_message_text(_pad(text), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))


async def _send_cards_content(bot, chat_id: int, user_id: int, custom_text: str = None):
    """Отправить список карт новым сообщением."""
    text, keyboard = await _build_cards_content(user_id, custom_text)
    msg = await bot.send_message(chat_id=chat_id, text=_pad(text), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    register_message(user_id, chat_id, msg.message_id)


@register_callback_handler("open_cards_unlocked")
async def cb_open_cards_unlocked(query, context, data, user, chat_id, bot):
    """Открыть карты без PIN-проверки (через кнопку Пропустить)."""
    # Завершаем процесс setpin_first, если он был
    if user.id in processes:
        del processes[user.id]
    await _show_cards_content(query)
