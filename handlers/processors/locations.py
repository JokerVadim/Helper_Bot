"""Locations domain processor."""
import asyncio
import logging
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from db import (
    db_get_locations, db_rename_location,
    db_get_locations_by_tag, db_get_location_tags_with_counts, db_get_location_tag,
)
from keyboards import btn_menu, btn_cancel
from handlers.session import register_message, start_process, finish_process
from handlers.processors import register_message_handler, register_callback_handler
from utils import md, _pad

logger = logging.getLogger(__name__)


# ─── Sort Mode ───────────────────────────────────────────────────────────────
_loc_sort_modes: dict[int, str] = {}  # user_id → "" | "up" | "down"

def _get_loc_sort_mode(user_id: int) -> str:
    return _loc_sort_modes.get(user_id, "")

def _set_loc_sort_mode(user_id: int, mode: str):
    if mode:
        _loc_sort_modes[user_id] = mode
    else:
        _loc_sort_modes.pop(user_id, None)


# ─── Action Mode ───────────────────────────────────────────────────────────
# Хранит режим действий: "" | "delete" | "rename" | "tags" | "location"
_loc_action_modes: dict[int, str] = {}

def _get_loc_action_mode(user_id: int) -> str:
    return _loc_action_modes.get(user_id, "")

def _set_loc_action_mode(user_id: int, mode: str):
    if mode:
        _loc_action_modes[user_id] = mode
    else:
        _loc_action_modes.pop(user_id, None)


# ─── Location ─────────────────────────────────────────────────────────────────

@register_message_handler("location")
async def handle_location_message(update, context, proc, state):
    from telegram import InlineKeyboardMarkup
    user = update.effective_user
    chat_id = update.effective_chat.id
    message = update.message or update.effective_message
    text = message.text.strip() if message.text else ""
    bot = context.bot
    register_message(user.id, chat_id, message.message_id)

    step = state.get("step")

    if step == "waiting_name":
        state["name"] = text
        state["step"] = "waiting_location"

        reply = await message.reply_text(
            f"📍 Название: *{md(text)}*\n\nТеперь отправь локацию (нажми скрепку → геолокация):",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        register_message(user.id, chat_id, reply.message_id)


# ─── Location Rename ──────────────────────────────────────────────────────────

@register_message_handler("location_rename")
async def handle_location_rename(update, context, proc, state):
    user = update.effective_user
    chat_id = update.effective_chat.id
    message = update.message or update.effective_message
    text = message.text.strip() if message.text else ""
    bot = context.bot
    register_message(user.id, chat_id, message.message_id)

    loc_id = state.get("loc_id")
    await db_rename_location( user.id, loc_id, text)
    await finish_process(bot, user.id, show_menu=False)
    from handlers.callbacks.locations import show_locations_menu
    await show_locations_menu(bot, user.id, "✅ Локация переименована!")


# ─── Callback Handlers ───────────────────────────────────────────────────────

async def _show_locations(query, custom_text: str = None, tag_id: Optional[int] = None):
    """Показать список локаций."""
    user = query.from_user
    action_mode = _get_loc_action_mode(user.id)
    sort_mode = _get_loc_sort_mode(user.id)
    tag = await db_get_location_tag( user.id, tag_id) if tag_id is not None else None
    if tag_id is not None and tag:
        locs = await db_get_locations_by_tag( user.id, tag_id)
    else:
        locs = await db_get_locations( user.id)
    keyboard = []
    for loc in locs:
        if sort_mode == "up":
            keyboard.append([InlineKeyboardButton(f"⬆️ {loc['name']}", callback_data=f"locmove_{loc['id']}_up")])
        elif sort_mode == "down":
            keyboard.append([InlineKeyboardButton(f"⬇️ {loc['name']}", callback_data=f"locmove_{loc['id']}_down")])
        elif action_mode == "delete":
            keyboard.append([InlineKeyboardButton(f"🗑 {loc['name']}", callback_data=f"delloc_{loc['id']}")])
        elif action_mode == "rename":
            keyboard.append([InlineKeyboardButton(f"✏️ {loc['name']}", callback_data=f"editlocname_{loc['id']}")])
        elif action_mode == "tags":
            keyboard.append([InlineKeyboardButton(f"🏷 {loc['name']}", callback_data=f"loctags_{loc['id']}")])
        elif action_mode == "location":
            keyboard.append([InlineKeyboardButton(f"📍 {loc['name']}", callback_data=f"editlocgeo_{loc['id']}")])
        else:
            keyboard.append([InlineKeyboardButton(f"{loc['name']}", callback_data=f"showloc_{loc['id']}")])

    if tag:
        text = f"📍 *Локации* / 🏷 *{md(tag['name'])}* ({len(locs)})"
    else:
        text = "📍 *Твои локации:*"
    if action_mode:
        _mode_labels = {"delete": "🗑 Удалить", "rename": "✏️ Редактировать", "tags": "🏷 Теги", "location": "📍 Координаты"}
        text += f"\n\n*Режим:* ✅ {_mode_labels.get(action_mode, action_mode)}"
    if custom_text:
        text = custom_text
    if not locs:
        text = "📍 *Локации* — пока нет сохранённых локаций."

    delete_lbl = "✅ 🗑 Удалить" if action_mode == "delete" else "🗑 Удалить"
    rename_lbl = "✅ ✏️ Редактировать" if action_mode == "rename" else "✏️ Редактировать"
    tags_lbl = "✅ 🏷 Теги" if action_mode == "tags" else "🏷 Теги"
    loc_lbl = "✅ 📍 Координаты" if action_mode == "location" else "📍 Координаты"
    sort_btn_label, sort_btn_mode = {
        "": ("🔢 Сортировка", "up"),
        "up": ("⬆️ Сортировка", "down"),
        "down": ("⬇️ Сортировка", "off"),
    }[sort_mode]
    keyboard.append([InlineKeyboardButton("✚ Добавить", callback_data="add_location"), InlineKeyboardButton(delete_lbl, callback_data="loctogglemode_delete")])
    keyboard.append([InlineKeyboardButton(rename_lbl, callback_data="loctogglemode_rename"), InlineKeyboardButton(loc_lbl, callback_data="loctogglemode_location")])
    keyboard.append([InlineKeyboardButton(tags_lbl, callback_data="loctogglemode_tags"), InlineKeyboardButton(sort_btn_label, callback_data=f"loctoggle_{sort_btn_mode}")])
    keyboard.append([btn_menu()])

    # Tag filter buttons (4 per row)
    all_tags = await db_get_location_tags_with_counts( user.id)
    all_tags = [t for t in all_tags if t["count"] > 0]
    if all_tags:
        tag_row = [InlineKeyboardButton("Все" if tag is not None else "• Все", callback_data="open_locations")]
        for t in all_tags:
            label = t["name"] if tag_id != t["id"] else f"• {t['name']}"
            tag_row.append(InlineKeyboardButton(label, callback_data=f"open_loctag_{t['id']}"))
        for i in range(0, len(tag_row), 4):
            keyboard.append(tag_row[i:i + 4])

    await query.edit_message_text(_pad(text), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))


@register_callback_handler("open_loctag_")
async def cb_open_loctag(query, context, data, user, chat_id, bot):
    tag_id = int(data.split("_")[2])
    await _show_locations(query, tag_id=tag_id)


# ─── Location Tags ────────────────────────────────────────────────────────────

@register_callback_handler("loctags_")
async def cb_loctags(query, context, data, user, chat_id, bot):
    loc_id = int(data.split("_")[1])
    from handlers.processors.tag_ui import show_tag_picker
    await show_tag_picker(query, user.id, chat_id, "location", loc_id)


@register_callback_handler("loctagedit_")
async def cb_loctagedit(query, context, data, user, chat_id, bot):
    parts = data.split("_")
    loc_id = int(parts[1])
    tag_id = int(parts[2])
    from db import db
    tags = await asyncio.to_thread(db.get_location_tags, user.id, loc_id)
    existing = {t["id"] for t in tags}
    if tag_id in existing:
        await asyncio.to_thread(db.remove_location_tag, user.id, loc_id, tag_id)
    else:
        tag = await asyncio.to_thread(db.get_location_tag, user.id, tag_id)
        if tag:
            await asyncio.to_thread(db.add_location_tag, user.id, loc_id, tag["name"])
    from handlers.processors.tag_ui import show_tag_picker
    await show_tag_picker(query, user.id, chat_id, "location", loc_id)


@register_callback_handler("loctagnew_")
async def cb_loctagnew(query, context, data, user, chat_id, bot):
    loc_id = int(data.split("_")[1])
    start_process(user.id, chat_id, "location_new_tag", {"step": "waiting_tag_name", "loc_id": loc_id}, query.message.message_id)
    await query.edit_message_text(
        _pad("🏷 *Новый тег*\n\nВведи название тега:"),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
    )


@register_message_handler("location_new_tag")
async def handle_location_new_tag(update, context, proc, state):
    from handlers.processors.tag_ui import show_tag_picker
    from telegram import InlineKeyboardMarkup
    user = update.effective_user
    chat_id = update.effective_chat.id
    message = update.message or update.effective_message
    text = message.text.strip() if message.text else ""
    bot = context.bot
    register_message(user.id, chat_id, message.message_id)

    if state.get("step") != "waiting_tag_name":
        return

    tag_name = text.strip()
    if not tag_name:
        reply = await message.reply_text(_pad("❌ Название тега не может быть пустым."), reply_markup=InlineKeyboardMarkup([[btn_cancel()]]))
        register_message(user.id, chat_id, reply.message_id)
        return

    from db import db
    loc_id = state["loc_id"]
    tag_id = await asyncio.to_thread(db.get_or_create_location_tag, user.id, tag_name)
    await asyncio.to_thread(db.add_location_tag, user.id, loc_id, tag_name)
    await finish_process(bot, user.id, show_menu=False)
    await show_tag_picker(bot, user.id, chat_id, "location", loc_id,
                          message=f"✅ Тег *{md(tag_name)}* добавлен.",
                          is_new_message=True)
