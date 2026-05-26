"""Supplies (Расходники) processor module."""

import logging
import uuid
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from db import (
    db_get_supplies, db_get_supply, db_save_supply,
    db_update_supply_name, db_update_supply_quantity,
    db_update_supply_min_quantity, db_update_supply_normal_quantity,
    db_update_supply_photo, db_delete_supply,
    db_supply_exists, db_update_supply_sort_order,
    db_get_supply_tags_with_counts, db_get_supplies_by_tag,
    db_get_supply_tags, db_get_supply_tag,
    db_add_supply_tag, db_remove_supply_tag,
    db_get_or_create_supply_tag,
    db_create_list, db_add_item, db_get_lists_for_user, db_delete_list,
)
from utils import md, _pad
from handlers.processors.tag_ui import tags_display_text, show_tag_picker
from keyboards import btn_menu, btn_cancel
from handlers.session import (
    register_message, start_process, finish_process,
    processes, user_messages,
)
from handlers.processors import register_message_handler, register_callback_handler

logger = logging.getLogger(__name__)

# ─── Sort mode storage ──────────────────────────────────────────────────────
_supply_sort_modes: dict[int, str] = {}  # user_id -> "" | "up" | "down"


def _get_sort_mode(user_id: int) -> str:
    return _supply_sort_modes.get(user_id, "")


def _set_sort_mode(user_id: int, mode: str):
    if mode:
        _supply_sort_modes[user_id] = mode
    else:
        _supply_sort_modes.pop(user_id, None)


def _cycle_sort_mode(user_id: int) -> str:
    """Циклический переключатель: "" → "up" → "down" → """""
    current = _get_sort_mode(user_id)
    next_mode = {"": "up", "up": "down", "down": ""}[current]
    _set_sort_mode(user_id, next_mode)
    return next_mode


# ─── Tag filter storage ─────────────────────────────────────────────────────
_supply_filter_tag: dict[int, int] = {}  # user_id -> tag_id


def _get_filter_tag(user_id: int) -> int | None:
    return _supply_filter_tag.get(user_id)


def _set_filter_tag(user_id: int, tag_id: int | None):
    if tag_id is not None:
        _supply_filter_tag[user_id] = tag_id
    else:
        _supply_filter_tag.pop(user_id, None)


# ─── Edit mode storage ──────────────────────────────────────────────────────
# When active, clicking an item triggers that action directly instead of viewing
_supply_edit_modes: dict[int, str] = {}  # user_id -> "" | "delete" | "name" | "qty" | "photo" | "min" | "incdec"


def _get_edit_mode(user_id: int) -> str:
    return _supply_edit_modes.get(user_id, "")


def _set_edit_mode(user_id: int, mode: str):
    if mode:
        _supply_edit_modes[user_id] = mode
    else:
        _supply_edit_modes.pop(user_id, None)


_EDIT_MODE_LABELS = {
    "delete": "🗑 Удалить",
    "name": "✏️ Название",
    "qty": "✏️ Кол-во",
    "photo": "✏️ Фото",
    "min": "✏️ Мин",
    "incdec": "+1/-1",
    "normal": "📊 Норма",
    "tags": "🏷 Теги",
}


def _supply_btn_label(s: dict) -> str:
    """Button label for a supply item."""
    ind = ""
    if s.get("min_quantity", 0) > 0 and s["quantity"] <= s["min_quantity"]:
        ind = "🔴 "
    return f"{ind}{s['name']} — {s['quantity']} шт"


# ─── Show supplies menu ─────────────────────────────────────────────────────

async def _build_supplies_content(
    user_id: int,
    message: str | None = None,
    tag_id: int | None = None,
) -> tuple[str, list, bool]:
    """Построить текст и клавиатуру меню расходников.

    Возвращает (text, keyboard, is_empty_no_tag) где is_empty_no_tag=True
    означает что расходников нет и фильтр по тегу не активен — нужно
    показать упрощённое сообщение.
    """
    sort_mode = _get_sort_mode(user_id)
    edit_mode = _get_edit_mode(user_id)

    # Получаем supplies — фильтрованные по тегу или все
    tag = None
    if tag_id is not None:
        _set_filter_tag(user_id, tag_id)
    else:
        tag_id = _get_filter_tag(user_id)
    if tag_id is not None:
        supplies = await db_get_supplies_by_tag(user_id, tag_id)
        tag = await db_get_supply_tag(user_id, tag_id)
    else:
        supplies = await db_get_supplies(user_id)

    text = _pad("📦 *Расходники*")
    if edit_mode:
        label = _EDIT_MODE_LABELS.get(edit_mode, edit_mode)
        text += f"\n\n*Режим:* ✅ {label}"
    if tag:
        text += f"\n\n🏷 Фильтр: *{md(tag['name'])}* ({len(supplies)})"
    if message:
        text += f"\n\n{message}"

    keyboard = []

    if not supplies:
        if tag:
            text += "\n\n❌ Нет расходников в этой категории."
        else:
            text = _pad("📦 Расходников пока нет.\n\nНажми ✚ Добавить, чтобы добавить первый.")

    # ── Item buttons ──────────────────────────────────────────────────────
    if sort_mode in ("up", "down"):
        arrow = "⬆️" if sort_mode == "up" else "⬇️"
        for s in supplies:
            label = _supply_btn_label(s)
            keyboard.append([InlineKeyboardButton(f"{arrow} {label}", callback_data=f"supply_sort_{s['id']}_{sort_mode}")])
    elif edit_mode:
        if edit_mode == "delete":
            for s in supplies:
                ind = "🔴 " if s.get("min_quantity", 0) > 0 and s["quantity"] <= s["min_quantity"] else ""
                keyboard.append([InlineKeyboardButton(f"{ind}🗑 {s['name']} — {s['quantity']} шт", callback_data=f"supply_item_del_{s['id']}")])
        elif edit_mode == "incdec":
            for s in supplies:
                label = _supply_btn_label(s)
                keyboard.append([InlineKeyboardButton(label, callback_data=f"supply_view_{s['id']}")])
                keyboard.append([
                    InlineKeyboardButton("+1", callback_data=f"supply_inc_{s['id']}"),
                    InlineKeyboardButton("-1", callback_data=f"supply_dec_{s['id']}"),
                ])
        elif edit_mode == "tags":
            for s in supplies:
                keyboard.append([InlineKeyboardButton(f"🏷 {s['name']} — {s['quantity']} шт", callback_data=f"supplytags_{s['id']}")])
        else:
            cb_prefix = f"supply_item_{edit_mode}_"
            for s in supplies:
                keyboard.append([InlineKeyboardButton(f"✏️ {s['name']} — {s['quantity']} шт", callback_data=f"{cb_prefix}{s['id']}")])
    else:
        for s in supplies:
            label = _supply_btn_label(s)
            keyboard.append([InlineKeyboardButton(label, callback_data=f"supply_view_{s['id']}")])

    # ── Bottom action bar ─────────────────────────────────────────────────
    incdec_lbl = "✅ +1/-1" if edit_mode == "incdec" else "+1/-1"
    sort_lbl = {"": "🔢 Сортировка", "up": "⬆️ Сортировка", "down": "⬇️ Сортировка"}[sort_mode]
    keyboard.append([
        InlineKeyboardButton("✚ Добавить", callback_data="supply_add"),
        InlineKeyboardButton("🗑 Удалить", callback_data="supply_mode_delete"),
        InlineKeyboardButton(incdec_lbl, callback_data="supply_mode_incdec"),
        InlineKeyboardButton(sort_lbl, callback_data="supply_sort_cycle"),
    ])

    name_lbl  = "✅ ✏️ Название" if edit_mode == "name"   else "✏️ Название"
    qty_lbl   = "✅ ✏️ Кол-во"   if edit_mode == "qty"    else "✏️ Кол-во"
    photo_lbl = "✅ ✏️ Фото"     if edit_mode == "photo"  else "✏️ Фото"
    min_lbl   = "✅ ✏️ Минимум" if edit_mode == "min" else "✏️ Минимум"
    keyboard.append([
        InlineKeyboardButton(name_lbl,  callback_data="supply_mode_name"),
        InlineKeyboardButton(qty_lbl,   callback_data="supply_mode_qty"),
        InlineKeyboardButton(photo_lbl, callback_data="supply_mode_photo"),
        InlineKeyboardButton(min_lbl,   callback_data="supply_mode_min"),
    ])

    normal_lbl = "✅ 📊 Норма" if edit_mode == "normal" else "📊 Норма"
    tags_lbl   = "✅ 🏷 Теги"   if edit_mode == "tags"   else "🏷 Теги"
    keyboard.append([
        InlineKeyboardButton(normal_lbl,          callback_data="supply_mode_normal"),
        InlineKeyboardButton(tags_lbl,            callback_data="supply_tags_mode"),
        InlineKeyboardButton("🛒 Докупить",        callback_data="supply_restock"),
    ])
    keyboard.append([btn_menu()])

    # ── Tag filter row ──────────────────────────────────────────────────────
    all_tags = await db_get_supply_tags_with_counts(user_id)
    all_tags = [t for t in all_tags if t["count"] > 0]
    if all_tags:
        tag_row = [InlineKeyboardButton("Все" if tag_id else "• Все", callback_data="open_supplies")]
        for t in all_tags:
            label = t["name"] if tag_id != t["id"] else f"• {t['name']}"
            tag_row.append(InlineKeyboardButton(label, callback_data=f"open_supplytag_{t['id']}"))
        for i in range(0, len(tag_row), 4):
            keyboard.append(tag_row[i:i + 4])

    return text, keyboard, False


async def _show_supplies(query, message: str | None = None, delete_old: list[int] | None = None, tag_id: int | None = None):
    """Показать меню расходников редактируя текущее сообщение."""
    text, keyboard, _ = await _build_supplies_content(query.from_user.id, message, tag_id)
    await _send_supplies_menu(query, text, keyboard)

    if delete_old:
        for msg_id in delete_old:
            try:
                await query.bot.delete_message(chat_id=query.message.chat_id, message_id=msg_id)
            except Exception:
                pass


async def _show_supplies_message(bot, user_id: int, chat_id: int, message: str | None = None, delete_old: list[int] | None = None, tag_id: int | None = None):
    """Показать меню расходников новым сообщением (для message-обработчиков)."""
    text, keyboard, _ = await _build_supplies_content(user_id, message, tag_id)
    msg = await bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    register_message(user_id, chat_id, msg.message_id)

    if delete_old:
        for msg_id in delete_old:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=msg_id)
            except Exception:
                pass


async def _send_supplies_menu(query, text: str, keyboard: list):
    try:
        await query.edit_message_text(
            text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception:
        msg = await query.message.reply_text(
            text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        register_message(query.from_user.id, query.message.chat_id, msg.message_id)


# ─── View single supply detail ──────────────────────────────────────────────

async def _show_supply_detail(bot, user_id: int, chat_id: int, supply_id: int):
    s = await db_get_supply(user_id, supply_id)
    if not s:
        return

    # Формируем текст
    name = s["name"]
    qty = s["quantity"]
    min_qty = s.get("min_quantity", 0)
    normal_qty = s.get("normal_quantity", 0)
    lines = [f"📦 *{md(name)}*"]
    lines.append(f"🔢 Количество: *{qty}* шт")
    if normal_qty > 0:
        lines.append(f"📊 Норма: *{normal_qty}* шт")
    if min_qty > 0:
        if qty <= min_qty:
            lines.append(f"⚠️ Мин. норма: *{min_qty}* шт 🔴")
        else:
            lines.append(f"⚠️ Мин. норма: *{min_qty}* шт")
    text = _pad("\n".join(lines))

    # Если есть фото — отправляем отдельным сообщением
    photo_msg_id = 0
    if s.get("photo_file_id"):
        try:
            file_id = s["photo_file_id"]
            file_type = s.get("photo_file_type", "photo")
            from handlers.callbacks.documents import _send_media_by_type
            sent = await _send_media_by_type(bot, chat_id, file_id, file_type)
            photo_msg_id = sent.message_id
        except Exception as e:
            logger.warning(f"Не удалось отправить фото расходника {supply_id}: {e}")

    # Теги
    tags_str = await tags_display_text(user_id, supply_id, "supply")
    if tags_str:
        text += f"\n\n{tags_str}"

    # Кнопка: [OK]
    markup = InlineKeyboardMarkup([[
        InlineKeyboardButton("OK", callback_data=f"supply_ok_{photo_msg_id}"),
    ]])

    msg = await bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=markup)
    register_message(user_id, chat_id, msg.message_id)

    if photo_msg_id:
        register_message(user_id, chat_id, photo_msg_id)


async def _cleanup_process_messages(bot, user_id: int, chat_id: int):
    """Удалить все сообщения текущего процесса для пользователя."""
    proc = processes.get(user_id)
    if not proc:
        return
    msg_ids = list(user_messages.get(user_id, []))
    for mid in msg_ids:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=mid)
        except Exception:
            pass
    user_messages.pop(user_id, None)


# ─── Callback handlers ──────────────────────────────────────────────────────
# Note: called from callbacks.py button_handler fallback:
#   handler(query, context, data, user, chat_id, bot)

@register_callback_handler("open_supplies")
async def _cb_open_supplies(query, context, data, user, chat_id, bot):
    _set_filter_tag(user.id, None)
    await _show_supplies(query)


@register_callback_handler("supply_add")
async def _cb_supply_add(query, context, data, user, chat_id, bot):
    user_id = user.id
    start_process(user_id, chat_id, "supply", {"step": "waiting_name"}, query.message.message_id)
    await query.edit_message_text(
        _pad("📦 *Новый расходник*\n\nВведи название (например: Салфетки, Туалетная бумага, Перчатки):"),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[btn_menu()]])
    )


@register_callback_handler("supply_mode_delete")
async def _cb_supply_mode_delete(query, context, data, user, chat_id, bot):
    """Toggle delete mode — clicking an item shows delete confirmation."""
    current = _get_edit_mode(user.id)
    if current == "delete":
        _set_edit_mode(user.id, "")
    else:
        _set_edit_mode(user.id, "delete")
    await _show_supplies(query)


@register_callback_handler("supply_item_del_")
async def _cb_supply_item_del(query, context, data, user, chat_id, bot):
    """Delete confirmation for a specific item (inline on same message)."""
    user_id = user.id
    supply_id = int(data.split("_")[3])
    s = await db_get_supply(user_id, supply_id)
    if not s:
        await query.answer("❌ Не найден", show_alert=True)
        return
    await query.edit_message_text(
        _pad(f"🗑 Удалить *{md(s['name'])}*?"),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Да, удалить", callback_data=f"supply_confirm_del_{supply_id}")],
            [InlineKeyboardButton("◀️ Отмена", callback_data="supply_mode_delete"), btn_menu()],
        ])
    )


@register_callback_handler("supply_confirm_del_")
async def _cb_supply_confirm_del(query, context, data, user, chat_id, bot):
    """Delete confirmation — actually delete the supply and return to menu."""
    user_id = user.id
    supply_id = int(data.split("_")[3])
    s = await db_get_supply(user_id, supply_id)
    name = s["name"] if s else "?"
    await db_delete_supply(user_id, supply_id)
    _set_edit_mode(user_id, "delete")  # keep delete mode active
    await _show_supplies(query, f"🗑 *{md(name)}* удалён!")


@register_callback_handler("supply_mode_name")
async def _cb_supply_mode_name(query, context, data, user, chat_id, bot):
    """Toggle rename mode — clicking an item directly starts rename."""
    current = _get_edit_mode(user.id)
    if current == "name":
        _set_edit_mode(user.id, "")
    else:
        _set_edit_mode(user.id, "name")
    await _show_supplies(query)


@register_callback_handler("supply_item_name_")
async def _cb_supply_item_name(query, context, data, user, chat_id, bot):
    """Start rename process for specific item (inline on same menu)."""
    user_id = user.id
    supply_id = int(data.split("_")[3])
    s = await db_get_supply(user_id, supply_id)
    if not s:
        await query.answer("❌ Не найден", show_alert=True)
        return
    start_process(user_id, chat_id, "supply_edit_name", {"supply_id": supply_id, "step": "waiting_name", "old_name": s["name"]}, query.message.message_id)
    await query.edit_message_text(
        _pad(f"✏️ *Редактировать название*\n\nТекущее: `{md(s['name'])}`\n\nВведи новое название:"),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[btn_menu()]])
    )


@register_callback_handler("supply_mode_qty")
async def _cb_supply_mode_qty(query, context, data, user, chat_id, bot):
    """Toggle qty edit mode — clicking an item directly starts qty edit."""
    current = _get_edit_mode(user.id)
    if current == "qty":
        _set_edit_mode(user.id, "")
    else:
        _set_edit_mode(user.id, "qty")
    await _show_supplies(query)


@register_callback_handler("supply_item_qty_")
async def _cb_supply_item_qty(query, context, data, user, chat_id, bot):
    """Start qty edit process for specific item."""
    user_id = user.id
    supply_id = int(data.split("_")[3])
    s = await db_get_supply(user_id, supply_id)
    if not s:
        await query.answer("❌ Не найден", show_alert=True)
        return
    start_process(user_id, chat_id, "supply_edit_qty", {"supply_id": supply_id, "step": "waiting_qty", "old_qty": s["quantity"]}, query.message.message_id)
    await query.edit_message_text(
        _pad(f"✏️ *Редактировать количество*\n\nРасходник: *{md(s['name'])}*\nТекущее: `{s['quantity']}` шт\n\nВведи новое количество (число):"),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[btn_menu()]])
    )


@register_callback_handler("supply_mode_photo")
async def _cb_supply_mode_photo(query, context, data, user, chat_id, bot):
    """Toggle photo edit mode."""
    current = _get_edit_mode(user.id)
    if current == "photo":
        _set_edit_mode(user.id, "")
    else:
        _set_edit_mode(user.id, "photo")
    await _show_supplies(query)


@register_callback_handler("supply_item_photo_")
async def _cb_supply_item_photo(query, context, data, user, chat_id, bot):
    """Start photo edit process for specific item."""
    user_id = user.id
    supply_id = int(data.split("_")[3])
    s = await db_get_supply(user_id, supply_id)
    if not s:
        await query.answer("❌ Не найден", show_alert=True)
        return
    start_process(user_id, chat_id, "supply_edit_photo", {"supply_id": supply_id, "step": "waiting_photo"}, query.message.message_id)
    await query.edit_message_text(
        _pad(f"📷 *Фото для расходника*\n\nРасходник: *{md(s['name'])}*\n\nОтправь фото (или введи «-» чтобы пропустить):"),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[btn_menu()]])
    )


# ─── Min quantity ────────────────────────────────────────────────────────────

@register_callback_handler("supply_mode_min")
async def _cb_supply_mode_min(query, context, data, user, chat_id, bot):
    """Toggle min quantity edit mode."""
    current = _get_edit_mode(user.id)
    if current == "min":
        _set_edit_mode(user.id, "")
    else:
        _set_edit_mode(user.id, "min")
    await _show_supplies(query)


@register_callback_handler("supply_mode_normal")
async def _cb_supply_mode_normal(query, context, data, user, chat_id, bot):
    """Toggle normal quantity edit mode."""
    current = _get_edit_mode(user.id)
    if current == "normal":
        _set_edit_mode(user.id, "")
    else:
        _set_edit_mode(user.id, "normal")
    await _show_supplies(query)


@register_callback_handler("supply_item_normal_")
async def _cb_supply_item_normal(query, context, data, user, chat_id, bot):
    """Start normal quantity edit for specific item."""
    user_id = user.id
    supply_id = int(data.split("_")[3])
    s = await db_get_supply(user_id, supply_id)
    if not s:
        await query.answer("❌ Не найден", show_alert=True)
        return
    current_normal = s.get("normal_quantity", 0)
    start_process(user_id, chat_id, "supply_edit_normal", {"supply_id": supply_id, "step": "waiting_normal"}, query.message.message_id)
    await query.edit_message_text(
        _pad(f"📊 *Норма для расходника*\n\nРасходник: *{md(s['name'])}*\n"
             f"Текущее количество: `{s['quantity']}` шт\n"
             f"Текущая норма: `{current_normal}` шт\n\n"
             f"Введи нормальное количество (сколько должно быть в наличии, 0 — отключить):"),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[btn_menu()]])
    )


@register_callback_handler("supply_item_min_")
async def _cb_supply_item_min(query, context, data, user, chat_id, bot):
    """Start min quantity edit for specific item."""
    user_id = user.id
    supply_id = int(data.split("_")[3])
    s = await db_get_supply(user_id, supply_id)
    if not s:
        await query.answer("❌ Не найден", show_alert=True)
        return
    current_min = s.get("min_quantity", 0)
    start_process(user_id, chat_id, "supply_edit_min", {"supply_id": supply_id, "step": "waiting_min"}, query.message.message_id)
    await query.edit_message_text(
        _pad(f"⚠️ *Мин. норма для расходника*\n\nРасходник: *{md(s['name'])}*\n"
             f"Текущий минимум: `{current_min}` шт\n"
             f"Количество сейчас: `{s['quantity']}` шт\n\n"
             f"Введи минимально-допустимое количество (целое число, 0 — отключить):"),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[btn_menu()]])
    )


# ─── +/- режим: инкремент/декремент ─────────────────────────────────────────

@register_callback_handler("supply_mode_incdec")
async def _cb_supply_incdec(query, context, data, user, chat_id, bot):
    """Toggle +/- mode — buttons appear under items on the same menu."""
    current = _get_edit_mode(user.id)
    if current == "incdec":
        _set_edit_mode(user.id, "")
    else:
        _set_edit_mode(user.id, "incdec")
    await _show_supplies(query)


@register_callback_handler("supply_inc_")
async def _cb_supply_inc(query, context, data, user, chat_id, bot):
    user_id = user.id
    supply_id = int(data.split("_")[2])
    s = await db_get_supply(user_id, supply_id)
    if not s:
        await query.answer("❌ Не найден", show_alert=True)
        return
    new_qty = s["quantity"] + 1
    await db_update_supply_quantity(user_id, supply_id, new_qty)
    await query.answer(f"✅ +1 = {new_qty}")
    await _refresh_incdec_keyboard(query, user_id)


@register_callback_handler("supply_dec_")
async def _cb_supply_dec(query, context, data, user, chat_id, bot):
    user_id = user.id
    supply_id = int(data.split("_")[2])
    s = await db_get_supply(user_id, supply_id)
    if not s:
        await query.answer("❌ Не найден", show_alert=True)
        return
    new_qty = max(0, s["quantity"] - 1)
    await db_update_supply_quantity(user_id, supply_id, new_qty)
    await query.answer(f"-1 = {new_qty}")
    await _refresh_incdec_keyboard(query, user_id)


async def _refresh_incdec_keyboard(query, user_id: int):
    """Refresh the menu keyboard in incdec mode with updated quantities."""
    try:
        supplies = await db_get_supplies(user_id)
        edit_mode = _get_edit_mode(user_id)
        sort_mode = _get_sort_mode(user_id)
        keyboard = []
        for s in supplies:
            label = _supply_btn_label(s)
            keyboard.append([InlineKeyboardButton(label, callback_data=f"supply_view_{s['id']}")])
            keyboard.append([                        InlineKeyboardButton("+1", callback_data=f"supply_inc_{s['id']}"),
                        InlineKeyboardButton("-1", callback_data=f"supply_dec_{s['id']}"),
            ])
        # Bottom action bar
        incdec_lbl = "✅ +1/-1" if edit_mode == "incdec" else "+1/-1"
        sort_lbl = {"": "🔢 Сортировка", "up": "⬆️ Сортировка", "down": "⬇️ Сортировка"}[sort_mode]
        keyboard.append([
            InlineKeyboardButton("✚ Добавить", callback_data="supply_add"),
            InlineKeyboardButton("🗑 Удалить", callback_data="supply_mode_delete"),
            InlineKeyboardButton(incdec_lbl, callback_data="supply_mode_incdec"),
            InlineKeyboardButton(sort_lbl, callback_data="supply_sort_cycle"),
        ])
        name_lbl = "✅ ✏️ Название" if edit_mode == "name" else "✏️ Название"
        qty_lbl = "✅ ✏️ Кол-во" if edit_mode == "qty" else "✏️ Кол-во"
        photo_lbl = "✅ ✏️ Фото" if edit_mode == "photo" else "✏️ Фото"
        min_lbl = "✅ ✏️ Минимум" if edit_mode == "min" else "✏️ Минимум"
        keyboard.append([
            InlineKeyboardButton(name_lbl, callback_data="supply_mode_name"),
            InlineKeyboardButton(qty_lbl, callback_data="supply_mode_qty"),
            InlineKeyboardButton(photo_lbl, callback_data="supply_mode_photo"),
            InlineKeyboardButton(min_lbl, callback_data="supply_mode_min"),
        ])
        normal_lbl = "✅ 📊 Норма" if edit_mode == "normal" else "📊 Норма"
        tags_lbl = "✅ 🏷 Теги" if edit_mode == "tags" else "🏷 Теги"
        keyboard.append([
            InlineKeyboardButton(normal_lbl, callback_data="supply_mode_normal"),
            InlineKeyboardButton(tags_lbl, callback_data="supply_tags_mode"),
            InlineKeyboardButton("🛒 Докупить", callback_data="supply_restock"),
        ])
        keyboard.append([btn_menu()])
        # ── Tag filter row ────────────────────────────────────────────────
        tag_id = _get_filter_tag(user_id)
        all_tags = await db_get_supply_tags_with_counts(user_id)
        all_tags = [t for t in all_tags if t["count"] > 0]
        if all_tags:
            tag_row = [InlineKeyboardButton("Все" if tag_id else "• Все", callback_data="open_supplies")]
            for t in all_tags:
                label = t["name"] if tag_id != t["id"] else f"• {t['name']}"
                tag_row.append(InlineKeyboardButton(label, callback_data=f"open_supplytag_{t['id']}"))
            for i in range(0, len(tag_row), 4):
                keyboard.append(tag_row[i:i + 4])
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        logger.warning(f"Refresh incdec keyboard failed: {e}")


@register_callback_handler("supply_ok_")
async def _cb_supply_ok(query, context, data, user, chat_id, bot):
    """OK button for supply detail — delete photo + detail message like Files section."""
    parts = data.split("_")
    photo_msg_id = int(parts[2])
    ok_msg_id = query.message.message_id

    msg_ids = [ok_msg_id]
    if photo_msg_id:
        msg_ids.append(photo_msg_id)

    try:
        await bot.delete_messages(chat_id=chat_id, message_ids=msg_ids)
    except Exception:
        # Fallback на удаление по одному
        for mid in msg_ids:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=mid)
            except Exception:
                pass


@register_callback_handler("supply_view_")
async def _cb_supply_view(query, context, data, user, chat_id, bot):
    supply_id = int(data.split("_")[2])
    # Меню остаётся на месте — показываем детали отдельным сообщением
    await _show_supply_detail(bot, user.id, chat_id, supply_id)


# ─── Сортировка ─────────────────────────────────────────────────────────────

@register_callback_handler("supply_sort_cycle")
async def _cb_supply_sort_cycle(query, context, data, user, chat_id, bot):
    """Циклический переключатель сортировки: "" → "up" → "down" → """""
    _cycle_sort_mode(user.id)
    await _show_supplies(query)


@register_callback_handler("supply_sort_")
async def _cb_supply_sort_move(query, context, data, user, chat_id, bot):
    # supply_sort_{id}_up / supply_sort_{id}_down
    parts = data.split("_")
    if len(parts) < 4:
        return
    user_id = user.id
    supply_id = int(parts[2])
    direction = parts[3]
    supplies = await db_get_supplies(user_id)
    ids = [s["id"] for s in supplies]
    if supply_id not in ids:
        return
    idx = ids.index(supply_id)
    if direction == "up" and idx > 0:
        ids[idx], ids[idx - 1] = ids[idx - 1], ids[idx]
    elif direction == "down" and idx < len(ids) - 1:
        ids[idx], ids[idx + 1] = ids[idx + 1], ids[idx]
    else:
        await query.answer("⛔ Крайняя позиция")
        return
    for i, sid in enumerate(ids):
        await db_update_supply_sort_order(user_id, sid, i)
    await _show_supplies(query)


# ─── Tag handlers ─────────────────────────────────────────────────────────────

@register_callback_handler("supply_tags_mode")
async def _cb_supply_tags_mode(query, context, data, user, chat_id, bot):
    """Toggle tags mode — clicking an item opens its tag picker."""
    current = _get_edit_mode(user.id)
    if current == "tags":
        _set_edit_mode(user.id, "")
    else:
        _set_edit_mode(user.id, "tags")
    await _show_supplies(query)



@register_callback_handler("open_supplytag_")
async def _cb_open_supplytag(query, context, data, user, chat_id, bot):
    """Filter supplies by tag."""
    tag_id = int(data.split("_")[2])
    _set_edit_mode(user.id, "")  # exit edit mode when filtering
    await _show_supplies(query, tag_id=tag_id)


@register_callback_handler("supplytags_")
async def _cb_supplytags(query, context, data, user, chat_id, bot):
    """Show tag picker for a supply."""
    supply_id = int(data.split("_")[1])
    await show_tag_picker(query, user.id, chat_id, "supply", supply_id)


@register_callback_handler("supplytagedit_")
async def _cb_supplytagedit(query, context, data, user, chat_id, bot):
    """Toggle a tag on/off for a supply."""
    parts = data.split("_")
    # Формат: supplytagedit_{supply_id}_{tag_id}
    supply_id = int(parts[1])
    tag_id = int(parts[2])
    user_id = user.id
    tags = await db_get_supply_tags(user_id, supply_id)
    existing = {t["id"] for t in tags}
    if tag_id in existing:
        await db_remove_supply_tag(user_id, supply_id, tag_id)
    else:
        tag = await db_get_supply_tag(user_id, tag_id)
        if tag:
            await db_add_supply_tag(user_id, supply_id, tag["name"])
    await show_tag_picker(query, user.id, chat_id, "supply", supply_id)


# ─── Докупить (Restock) ────────────────────────────────────────────────────

@register_callback_handler("supply_restock")
async def _cb_supply_restock(query, context, data, user, chat_id, bot):
    """Create/replace a shopping list with items that need restocking.
    If a tag filter is active, creates a tag-specific list (e.g. "Докупить - Бумага").
    """
    user_id = user.id

    # Определяем активный тег-фильтр
    tag_id = _get_filter_tag(user_id)
    tag_name = None
    if tag_id is not None:
        tag = await db_get_supply_tag(user_id, tag_id)
        if tag:
            tag_name = tag["name"]

    # Берём supplies — если фильтр активен, только по тегу
    if tag_id is not None:
        supplies = await db_get_supplies_by_tag(user_id, tag_id)
    else:
        supplies = await db_get_supplies(user_id)

    # Filter supplies where quantity < normal_quantity and normal_quantity > 0
    to_buy = []
    for s in supplies:
        normal = s.get("normal_quantity", 0)
        if normal > 0 and s["quantity"] < normal:
            diff = normal - s["quantity"]
            to_buy.append((s["name"], diff))

    if not to_buy:
        await _show_supplies(query, "✅ Всё в норме! Докупать ничего не нужно.")
        return

    # Формируем имя списка в зависимости от фильтра
    if tag_name:
        list_name = f"Докупить - {tag_name}"
    else:
        list_name = "Докупить расходники"

    # Delete old list with the same name if exists
    existing_lists = await db_get_lists_for_user(user_id)
    for lst in existing_lists:
        if lst["name"] == list_name:
            await db_delete_list(lst["list_id"])
            break

    # Create new list
    list_id = str(uuid.uuid4())
    await db_create_list(list_id, "shopping", list_name, user_id)

    # Add items
    for name, diff in to_buy:
        item_text = f"{name} — {diff} шт"
        await db_add_item(list_id, user_id, item_text, "📦")

    await _show_supplies(query, f"🛒 Список *«{list_name}»* создан!\nДобавлено *{len(to_buy)}* позиций.")


@register_callback_handler("supplytagnew_")
async def _cb_supplytagnew(query, context, data, user, chat_id, bot):
    """Create a new tag for a supply."""
    supply_id = int(data.split("_")[1])
    start_process(user.id, chat_id, "supply_new_tag", {"step": "waiting_tag_name", "supply_id": supply_id}, query.message.message_id)
    await query.edit_message_text(
        _pad("🏷 *Новый тег*\n\nВведи название тега:"),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
    )


@register_message_handler("supply_new_tag")
async def _msg_supply_new_tag(update, context, proc, state):
    user = update.effective_user
    chat_id = update.effective_chat.id
    message = update.message or update.effective_message
    text = message.text.strip() if message.text else ""
    bot = context.bot
    register_message(user.id, chat_id, message.message_id)

    if state.get("step") != "waiting_tag_name":
        return

    if not text:
        reply = await message.reply_text(_pad("❌ Название тега не может быть пустым."), reply_markup=InlineKeyboardMarkup([[btn_cancel()]]))
        register_message(user.id, chat_id, reply.message_id)
        return

    supply_id = state["supply_id"]
    tag_id = await db_get_or_create_supply_tag(user.id, text)
    await db_add_supply_tag(user.id, supply_id, text)
    await finish_process(bot, user.id, show_menu=False)
    await show_tag_picker(bot, user.id, chat_id, "supply", supply_id,
                          message=f"✅ Тег *{md(text)}* добавлен.",
                          is_new_message=True)


# ─── Message handler ────────────────────────────────────────────────────────

@register_message_handler("supply")
async def _msg_supply(update, context, proc, state):
    user = update.effective_user
    chat_id = update.effective_chat.id
    bot = context.bot
    text = update.message.text.strip() if update.message.text else ""
    step = state.get("step", "")

    if step == "waiting_name":
        if not text:
            msg = await update.message.reply_text(
                _pad("❗️ Название не может быть пустым. Введи название расходника:"),
                reply_markup=InlineKeyboardMarkup([[btn_menu()]])
            )
            register_message(user.id, chat_id, update.message.message_id)
            register_message(user.id, chat_id, msg.message_id)
            return

        exists = await db_supply_exists(user.id, text)
        if exists:
            msg = await update.message.reply_text(
                _pad(f"❗️ Расходник *{md(text)}* уже существует."),
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[btn_menu()]])
            )
            register_message(user.id, chat_id, update.message.message_id)
            register_message(user.id, chat_id, msg.message_id)
            return

        # Сохраняем временно с quantity=0 (потом обновим)
        supply_id = await db_save_supply(user.id, text, 0)
        state["supply_id"] = supply_id
        state["supply_name"] = text
        state["step"] = "waiting_qty"
        # Удаляем старые сообщения перед следующим шагом
        await _cleanup_process_messages(bot, user.id, chat_id)
        register_message(user.id, chat_id, update.message.message_id)
        msg = await update.message.reply_text(
            _pad(f"✅ *{md(text)}*\n\nТеперь введи количество (целое число, например: 5):"),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[btn_menu()]])
        )
        register_message(user.id, chat_id, msg.message_id)

    elif step == "waiting_qty":
        try:
            qty = int(text)
            if qty < 0:
                raise ValueError
        except (ValueError, TypeError):
            msg = await update.message.reply_text(
                _pad("❗️ Введи целое неотрицательное число (например: 5)."),
                reply_markup=InlineKeyboardMarkup([[btn_menu()]])
            )
            register_message(user.id, chat_id, update.message.message_id)
            register_message(user.id, chat_id, msg.message_id)
            return

        supply_id = state.get("supply_id")
        await db_update_supply_quantity(user.id, supply_id, qty)
        state["step"] = "waiting_min_qty"
        # Удаляем старые сообщения перед следующим шагом
        await _cleanup_process_messages(bot, user.id, chat_id)
        register_message(user.id, chat_id, update.message.message_id)
        msg = await update.message.reply_text(
            _pad(f"✅ Количество: *{qty}* шт\n\nТеперь введи **минимально-допустимое количество** (целое число, 0 — без минимума):\n\n"
                 f"При достижении этого минимума на кнопке загорится 🔴 индикатор."),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[btn_menu()]])
        )
        register_message(user.id, chat_id, msg.message_id)

    elif step == "waiting_min_qty":
        try:
            min_qty = int(text)
            if min_qty < 0:
                raise ValueError
        except (ValueError, TypeError):
            msg = await update.message.reply_text(
                _pad("❗️ Введи целое неотрицательное число (например: 3). Или 0 — без минимума."),
                reply_markup=InlineKeyboardMarkup([[btn_menu()]])
            )
            register_message(user.id, chat_id, update.message.message_id)
            register_message(user.id, chat_id, msg.message_id)
            return

        supply_id = state.get("supply_id")
        await db_update_supply_min_quantity(user.id, supply_id, min_qty)
        state["step"] = "waiting_normal"
        # Удаляем старые сообщения перед следующим шагом
        await _cleanup_process_messages(bot, user.id, chat_id)
        register_message(user.id, chat_id, update.message.message_id)
        msg = await update.message.reply_text(
            _pad(f"✅ Мин. норма: *{min_qty}* шт\n\nТеперь введи **нормальное количество** (сколько должно быть в наличии, 0 — без нормы):\n\n"
                 f"При нажатии «🛒 Докупить» бот подсчитает разницу между нормой и текущим количеством и добавит в список покупок."),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[btn_menu()]])
        )
        register_message(user.id, chat_id, msg.message_id)

    elif step == "waiting_normal":
        try:
            normal_qty = int(text)
            if normal_qty < 0:
                raise ValueError
        except (ValueError, TypeError):
            msg = await update.message.reply_text(
                _pad("❗️ Введи целое неотрицательное число (0 — без нормы)."),
                reply_markup=InlineKeyboardMarkup([[btn_menu()]])
            )
            register_message(user.id, chat_id, update.message.message_id)
            register_message(user.id, chat_id, msg.message_id)
            return

        supply_id = state.get("supply_id")
        await db_update_supply_normal_quantity(user.id, supply_id, normal_qty)
        state["step"] = "waiting_photo"
        # Удаляем старые сообщения перед следующим шагом
        await _cleanup_process_messages(bot, user.id, chat_id)
        register_message(user.id, chat_id, update.message.message_id)
        msg = await update.message.reply_text(
            _pad(f"✅ Норма: *{normal_qty}* шт\n\nТеперь отправь **фото** расходника (или введи «-» чтобы пропустить):"),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[btn_menu()]])
        )
        register_message(user.id, chat_id, msg.message_id)

    elif step == "waiting_photo":
        supply_id = state.get("supply_id")
        supply_name = state.get("supply_name", "")
        file_id = None
        file_type = "photo"

        if text == "-":
            # Пропускаем фото
            pass
        elif update.message.photo:
            photo = update.message.photo[-1]
            file_id = photo.file_id
        elif update.message.document:
            file_id = update.message.document.file_id
            file_type = "document"
        else:
            msg = await update.message.reply_text(
                _pad("❗️ Отправь фото, документ или введи «-» чтобы пропустить."),
                reply_markup=InlineKeyboardMarkup([[btn_menu()]])
            )
            register_message(user.id, chat_id, update.message.message_id)
            register_message(user.id, chat_id, msg.message_id)
            return

        if file_id:
            await db_update_supply_photo(user.id, supply_id, file_id, file_type)

        # Удаляем сообщение с вводом пользователя
        try:
            await bot.delete_message(chat_id=chat_id, message_id=update.message.message_id)
        except Exception:
            pass
        # Удаляем все диалоговые сообщения процесса
        await _cleanup_process_messages(bot, user.id, chat_id)
        # Завершаем процесс
        await finish_process(bot, user.id, show_menu=False)
        # Показываем меню расходников
        await _show_supplies_message(bot, user.id, chat_id, f"✅ *{md(supply_name)}* добавлен!")


@register_message_handler("supply_edit_name")
async def _msg_supply_edit_name(update, context, proc, state):
    user = update.effective_user
    chat_id = update.effective_chat.id
    bot = context.bot
    text = update.message.text.strip()
    step = state.get("step", "")
    supply_id = state.get("supply_id")

    if step == "waiting_name":
        if not text:
            msg = await update.message.reply_text(
                _pad("❗️ Название не может быть пустым."),
                reply_markup=InlineKeyboardMarkup([[btn_menu()]])
            )
            register_message(user.id, chat_id, msg.message_id)
            return
        await db_update_supply_name(user.id, supply_id, text)
        # Удаляем сообщение с вводом пользователя
        try:
            await bot.delete_message(chat_id=chat_id, message_id=update.message.message_id)
        except Exception:
            pass
        # Удаляем все диалоговые сообщения процесса
        await _cleanup_process_messages(bot, user.id, chat_id)
        # Завершаем процесс
        await finish_process(bot, user.id, show_menu=False)
        await _show_supplies_message(bot, user.id, chat_id, f"✏️ Название изменено на *{md(text)}*")


@register_message_handler("supply_edit_qty")
async def _msg_supply_edit_qty(update, context, proc, state):
    user = update.effective_user
    chat_id = update.effective_chat.id
    bot = context.bot
    text = update.message.text.strip()
    supply_id = state.get("supply_id")
    step = state.get("step", "")

    if step == "waiting_qty":
        try:
            qty = int(text)
            if qty < 0:
                raise ValueError
        except (ValueError, TypeError):
            msg = await update.message.reply_text(
                _pad("❗️ Введи целое неотрицательное число."),
                reply_markup=InlineKeyboardMarkup([[btn_menu()]])
            )
            register_message(user.id, chat_id, msg.message_id)
            return
        await db_update_supply_quantity(user.id, supply_id, qty)
        # Удаляем сообщение с вводом пользователя
        try:
            await bot.delete_message(chat_id=chat_id, message_id=update.message.message_id)
        except Exception:
            pass
        # Удаляем все диалоговые сообщения процесса
        await _cleanup_process_messages(bot, user.id, chat_id)
        # Завершаем процесс
        await finish_process(bot, user.id, show_menu=False)
        await _show_supplies_message(bot, user.id, chat_id, f"✏️ Количество изменено на *{qty}* шт")


@register_message_handler("supply_edit_photo")
async def _msg_supply_edit_photo(update, context, proc, state):
    user = update.effective_user
    chat_id = update.effective_chat.id
    bot = context.bot
    text = update.message.text.strip() if update.message.text else ""
    supply_id = state.get("supply_id")

    file_id = None
    file_type = "photo"

    if text == "-":
        # Пропускаем
        try:
            await bot.delete_message(chat_id=chat_id, message_id=update.message.message_id)
        except Exception:
            pass
        await _cleanup_process_messages(bot, user.id, chat_id)
        await finish_process(bot, user.id, show_menu=False)
        await _show_supplies_message(bot, user.id, chat_id, "⏭️ Фото пропущено")
        return

    if update.message.photo:
        photo = update.message.photo[-1]
        file_id = photo.file_id
    elif update.message.document:
        file_id = update.message.document.file_id
        file_type = "document"
    else:
        msg = await update.message.reply_text(
            _pad("❗️ Отправь фото, документ или введи «-» чтобы пропустить."),
            reply_markup=InlineKeyboardMarkup([[btn_menu()]])
        )
        register_message(user.id, chat_id, msg.message_id)
        return

    await db_update_supply_photo(user.id, supply_id, file_id, file_type)
    # Удаляем сообщение с вводом пользователя
    try:
        await bot.delete_message(chat_id=chat_id, message_id=update.message.message_id)
    except Exception:
        pass
    # Удаляем все диалоговые сообщения процесса
    await _cleanup_process_messages(bot, user.id, chat_id)
    # Завершаем процесс
    await finish_process(bot, user.id, show_menu=False)
    await _show_supplies_message(bot, user.id, chat_id, "✅ Фото сохранено!")


@register_message_handler("supply_edit_normal")
async def _msg_supply_edit_normal(update, context, proc, state):
    user = update.effective_user
    chat_id = update.effective_chat.id
    bot = context.bot
    text = update.message.text.strip()
    supply_id = state.get("supply_id")
    step = state.get("step", "")

    if step == "waiting_normal":
        try:
            normal_qty = int(text)
            if normal_qty < 0:
                raise ValueError
        except (ValueError, TypeError):
            msg = await update.message.reply_text(
                _pad("❗️ Введи целое неотрицательное число (0 — без нормы)."),
                reply_markup=InlineKeyboardMarkup([[btn_menu()]])
            )
            register_message(user.id, chat_id, msg.message_id)
            return
        await db_update_supply_normal_quantity(user.id, supply_id, normal_qty)
        # Удаляем сообщение с вводом пользователя
        try:
            await bot.delete_message(chat_id=chat_id, message_id=update.message.message_id)
        except Exception:
            pass
        # Удаляем все диалоговые сообщения процесса
        await _cleanup_process_messages(bot, user.id, chat_id)
        # Завершаем процесс
        await finish_process(bot, user.id, show_menu=False)
        if normal_qty > 0:
            await _show_supplies_message(bot, user.id, chat_id, f"📊 Норма установлена: *{normal_qty}* шт")
        else:
            await _show_supplies_message(bot, user.id, chat_id, "✅ Норма отключена")


@register_message_handler("supply_edit_min")
async def _msg_supply_edit_min(update, context, proc, state):
    user = update.effective_user
    chat_id = update.effective_chat.id
    bot = context.bot
    text = update.message.text.strip()
    supply_id = state.get("supply_id")
    step = state.get("step", "")

    if step == "waiting_min":
        try:
            min_qty = int(text)
            if min_qty < 0:
                raise ValueError
        except (ValueError, TypeError):
            msg = await update.message.reply_text(
                _pad("❗️ Введи целое неотрицательное число (0 — без минимума)."),
                reply_markup=InlineKeyboardMarkup([[btn_menu()]])
            )
            register_message(user.id, chat_id, msg.message_id)
            return
        await db_update_supply_min_quantity(user.id, supply_id, min_qty)
        # Удаляем сообщение с вводом пользователя
        try:
            await bot.delete_message(chat_id=chat_id, message_id=update.message.message_id)
        except Exception:
            pass
        # Удаляем все диалоговые сообщения процесса
        await _cleanup_process_messages(bot, user.id, chat_id)
        # Завершаем процесс
        await finish_process(bot, user.id, show_menu=False)
        if min_qty > 0:
            await _show_supplies_message(bot, user.id, chat_id, f"⚠️ Мин. норма установлена: *{min_qty}* шт")
        else:
            await _show_supplies_message(bot, user.id, chat_id, "✅ Мин. норма отключена")
