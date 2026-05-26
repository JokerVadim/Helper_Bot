"""Reusable tag UI components for any domain.

Предоставляет:
- tag_detail_text() — отформатированная строка тегов для отображения в деталях
- show_tag_picker() — интерактивный пикер тегов с чекбоксами
- create_tag_process() — обработка создания нового тега на лету
"""
import asyncio
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest

from utils import md, _pad

logger = logging.getLogger(__name__)


def get_tag_getter(domain: str):
    """Вернуть пару функций (get_tags, get_tags_with_counts, get_tag, add_tag, remove_tag, get_or_create_tag)
    для указанного домена.
    """
    from db import db
    mappers = {
        "note": (db.get_note_tags, db.get_note_tags_with_counts, db.get_note_tag,
                 db.add_note_tag, db.remove_note_tag, db.get_or_create_note_tag),
        "reminder": (db.get_reminder_tags, db.get_reminder_tags_with_active_counts, db.get_reminder_tag,
                     db.add_reminder_tag, db.remove_reminder_tag, db.get_or_create_reminder_tag),
        "location": (db.get_location_tags, db.get_location_tags_with_counts, db.get_location_tag,
                     db.add_location_tag, db.remove_location_tag, db.get_or_create_location_tag),
        "supply": (db.get_supply_tags, db.get_supply_tags_with_counts, db.get_supply_tag,
                    db.add_supply_tag, db.remove_supply_tag, db.get_or_create_supply_tag),
    }
    if domain not in mappers:
        raise ValueError(f"Unknown domain: {domain}")
    return mappers[domain]


async def tags_display_text(user_id: int, obj_id: int, domain: str) -> str:
    """Вернуть строку с тегами объекта, например:
    🏷 работа, личное
    или пустую строку, если тегов нет (кроме разное).
    """
    get_tags, _, _, _, _, _ = get_tag_getter(domain)
    tags = await asyncio.to_thread(get_tags, user_id, obj_id)
    visible = [md(t["name"]) for t in tags if t["name"].lower() != "разное"]
    if not visible:
        return ""
    return "🏷 " + ", ".join(visible)


async def show_tag_picker(query_or_bot, user_id: int, chat_id: int,
                          domain: str, obj_id: int,
                          selected_tag_ids: set[int] | None = None,
                          message: str | None = None,
                          is_new_message: bool = False):
    """Показать интерактивный пикер тегов.

    Args:
        query_or_bot: telegram.Update.callback_query или bot
        user_id: ID пользователя
        chat_id: ID чата
        domain: "note" | "reminder" | "location"
        obj_id: ID объекта (заметки, напоминания, локации)
        selected_tag_ids: Предварительно выбранные ID тегов
        message: Дополнительный текст
        is_new_message: Если True — отправляет новое сообщение, иначе редактирует
    """
    get_tags, get_tags_with_counts, _, _, _, _ = get_tag_getter(domain)
    tags = await asyncio.to_thread(get_tags, user_id, obj_id)
    all_tags = await asyncio.to_thread(get_tags_with_counts, user_id)
    if selected_tag_ids is None:
        selected_tag_ids = {t["id"] for t in tags}

    keyboard = []
    for tag in all_tags:
        if tag["count"] == 0:
            continue
        marker = "☑️" if tag["id"] in selected_tag_ids else "☐"
        prefix_map = {"note": "notetagedit", "reminder": "remindertagedit", "location": "loctagedit", "supply": "supplytagedit"}
        cb_prefix = prefix_map[domain]
        keyboard.append([InlineKeyboardButton(
            f"{marker} {tag['name']} ({tag['count']})",
            callback_data=f"{cb_prefix}_{obj_id}_{tag['id']}"
        )])

    new_tag_prefix = {"note": "notetagnew", "reminder": "remindertagnew", "location": "loctagnew", "supply": "supplytagnew"}

    domain_back = {"note": "open_notes", "reminder": "open_reminders", "location": "open_locations", "supply": "open_supplies"}
    keyboard.append([InlineKeyboardButton("➕ Новый тег", callback_data=f"{new_tag_prefix[domain]}_{obj_id}"),
                  InlineKeyboardButton("◀️ Назад", callback_data=domain_back[domain])])

    title_map = {"note": "📝", "reminder": "⏰", "location": "📍", "supply": "📦"}
    text = _pad(f"{title_map[domain]} *Теги*")
    if message:
        text += f"\n\n{message}"
    if not all_tags:
        text += "\n\nТегов пока нет. Создайте новый тег."

    markup = InlineKeyboardMarkup(keyboard)
    if is_new_message:
        from handlers.session import register_message
        bot = query_or_bot if hasattr(query_or_bot, 'send_message') else None
        if not bot:
            return
        msg = await bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown", reply_markup=markup)
        register_message(user_id, chat_id, msg.message_id)
    else:
        try:
            await query_or_bot.edit_message_text(text, parse_mode="Markdown", reply_markup=markup)
        except BadRequest as e:
            if "Message is not modified" in str(e):
                pass
            else:
                raise
