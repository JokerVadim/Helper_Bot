"""Notes domain processor."""
import asyncio
import logging
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from db import db_get_notes, db_save_note, db_update_note, db_note_exists, db_get_notes_by_tag, db_get_note_tags_with_counts, db_get_note_tag
from keyboards import btn_menu, btn_cancel, show_main_menu
from handlers.session import register_message, start_process, finish_process
from handlers.processors import register_message_handler, register_callback_handler
from handlers.processors.tag_ui import tags_display_text
from utils import md, _pad

logger = logging.getLogger(__name__)

# ─── Action Mode ──────────────────────────────────────────────────────────────
_note_action_modes: dict[int, str] = {}

def _get_note_action_mode(user_id: int) -> str:
    return _note_action_modes.get(user_id, "")

def _set_note_action_mode(user_id: int, mode: str):
    if mode:
        _note_action_modes[user_id] = mode
    else:
        _note_action_modes.pop(user_id, None)


# ─── Message Handlers ────────────────────────────────────────────────────────

@register_message_handler("note")
async def handle_note_message(update, context, proc, state):
    from telegram import InlineKeyboardMarkup
    user = update.effective_user
    chat_id = update.effective_chat.id
    message = update.message or update.effective_message
    text = message.text.strip() if message.text else ""
    bot = context.bot
    register_message(user.id, chat_id, message.message_id)

    step = state.get("step")

    if step == "waiting_name":
        if await db_note_exists(user.id, text):
            reply = await message.reply_text(
                _pad("⚠️ Заметка с таким названием уже есть!"),
                reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
            )
            register_message(user.id, chat_id, reply.message_id)
            return
        state["name"] = text
        state["step"] = "waiting_content"
        reply = await message.reply_text(
            _pad(f"📝 Название: *{md(text)}*\n\nТеперь введи текст заметки:"),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        register_message(user.id, chat_id, reply.message_id)
        return

    if step == "waiting_content":
        name = state.get("name", "Заметка")
        await db_save_note(user.id, name, text)
        await finish_process(bot, user.id, show_menu=False)
        await show_main_menu(bot, user.id, f"✅ Заметка *{md(name)}* сохранена!")


@register_message_handler("note_edit_name")
async def handle_note_edit_name_message(update, context, proc, state):
    from handlers.callbacks.notes import show_note_detail
    from telegram import InlineKeyboardMarkup
    user = update.effective_user
    chat_id = update.effective_chat.id
    message = update.message or update.effective_message
    text = message.text.strip() if message.text else ""
    bot = context.bot
    register_message(user.id, chat_id, message.message_id)

    note_id = state.get("note_id")

    if await db_note_exists(user.id, text):
        reply = await message.reply_text(
            _pad("⚠️ Заметка с таким названием уже есть!"),
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        register_message(user.id, chat_id, reply.message_id)
        return

    notes = await db_get_notes(user.id)
    note = next((n for n in notes if n["id"] == note_id), None)
    if note:
        await db_update_note(user.id, note_id, text, note["content"])
    await finish_process(bot, user.id, show_menu=False)
    if state.get("from_list"):
        await _show_notes_message(bot, user.id, f"✅ Название изменено: {md(text)}")
    else:
        await show_note_detail(bot, user.id, note_id, f"✅ Название изменено: {md(text)}")


@register_message_handler("note_edit_content")
async def handle_note_edit_content_message(update, context, proc, state):
    from handlers.callbacks.notes import show_note_detail
    user = update.effective_user
    chat_id = update.effective_chat.id
    message = update.message or update.effective_message
    text = message.text.strip() if message.text else ""
    bot = context.bot
    register_message(user.id, chat_id, message.message_id)

    note_id = state.get("note_id")

    notes = await db_get_notes(user.id)
    note = next((n for n in notes if n["id"] == note_id), None)
    if note:
        await db_update_note(user.id, note_id, note["name"], text)
    await finish_process(bot, user.id, show_menu=False)
    await show_note_detail(bot, user.id, note_id, "✅ Текст заметки обновлён!")


# ─── Callback Handlers ───────────────────────────────────────────────────────

async def _show_notes(query, custom_text: str = None, tag_id: Optional[int] = None):
    """Показать список заметок."""
    user = query.from_user
    tag = await db_get_note_tag(user.id, tag_id) if tag_id is not None else None
    if tag_id is not None and tag:
        notes = await db_get_notes_by_tag(user.id, tag_id)
    else:
        notes = await db_get_notes(user.id)

    action_mode = _get_note_action_mode(user.id)

    keyboard = []
    for note in notes:
        if action_mode == "delete":
            btn = InlineKeyboardButton(f"🗑 {note['name']}", callback_data=f"delnote_{note['id']}")
        elif action_mode == "tags":
            btn = InlineKeyboardButton(f"🏷 {note['name']}", callback_data=f"notetags_{note['id']}")
        else:
            btn = InlineKeyboardButton(note['name'], callback_data=f"shownote_{note['id']}")
        keyboard.append([btn])

    if tag:
        text = f"📝 *Заметки* / 🏷 *{md(tag['name'])}* ({len(notes)})"
    else:
        text = "📝 *Твои заметки:*"
    if action_mode:
        _mode_labels = {"delete": "🗑 Удалить", "tags": "🏷 Теги"}
        text += f"\n\n*Режим:* ✅ {_mode_labels.get(action_mode, action_mode)}"
    if custom_text:
        text = custom_text
    if not notes:
        text = "📝 *Заметки* — пока нет сохранённых заметок."

    delete_lbl = "✅ 🗑 Удалить" if action_mode == "delete" else "🗑 Удалить"
    tags_lbl = "✅ 🏷 Теги" if action_mode == "tags" else "🏷 Теги"
    keyboard.append([InlineKeyboardButton("✚ Добавить", callback_data="add_note"), InlineKeyboardButton(tags_lbl, callback_data="notestogglemode_tags"), InlineKeyboardButton(delete_lbl, callback_data="notestogglemode_delete")])
    keyboard.append([btn_menu()])

    # Tag filter buttons (4 per row)
    all_tags = await db_get_note_tags_with_counts(user.id)
    all_tags = [t for t in all_tags if t["count"] > 0]
    if all_tags:
        tag_row = [InlineKeyboardButton("Все" if tag is not None else "• Все", callback_data="open_notes")]
        for t in all_tags:
            label = t["name"] if tag_id != t["id"] else f"• {t['name']}"
            tag_row.append(InlineKeyboardButton(label, callback_data=f"open_notetag_{t['id']}"))
        for i in range(0, len(tag_row), 4):
            keyboard.append(tag_row[i:i + 4])

    await query.edit_message_text(_pad(text), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))


async def _show_notes_message(bot, user_id: int, custom_text: str = None, tag_id: Optional[int] = None):
    """Показать список заметок новым сообщением (для вызова из bot.py при завершении процесса)."""
    from handlers.session import register_message

    tag = await db_get_note_tag(user_id, tag_id) if tag_id is not None else None
    if tag_id is not None and tag:
        notes = await db_get_notes_by_tag(user_id, tag_id)
    else:
        notes = await db_get_notes(user_id)

    action_mode = _get_note_action_mode(user_id)

    keyboard = []
    for note in notes:
        if action_mode == "delete":
            btn = InlineKeyboardButton(f"🗑 {note['name']}", callback_data=f"delnote_{note['id']}")
        elif action_mode == "tags":
            btn = InlineKeyboardButton(f"🏷 {note['name']}", callback_data=f"notetags_{note['id']}")
        else:
            btn = InlineKeyboardButton(note['name'], callback_data=f"shownote_{note['id']}")
        keyboard.append([btn])

    if tag:
        text = f"📝 *Заметки* / 🏷 *{md(tag['name'])}* ({len(notes)})"
    else:
        text = "📝 *Твои заметки:*"
    if action_mode:
        _mode_labels = {"delete": "🗑 Удалить", "tags": "🏷 Теги"}
        text += f"\n\n*Режим:* ✅ {_mode_labels.get(action_mode, action_mode)}"
    if custom_text:
        text = custom_text
    if not notes:
        text = "📝 *Заметки* — пока нет сохранённых заметок."

    delete_lbl = "✅ 🗑 Удалить" if action_mode == "delete" else "🗑 Удалить"
    tags_lbl = "✅ 🏷 Теги" if action_mode == "tags" else "🏷 Теги"
    keyboard.append([InlineKeyboardButton("✚ Добавить", callback_data="add_note"), InlineKeyboardButton(tags_lbl, callback_data="notestogglemode_tags"), InlineKeyboardButton(delete_lbl, callback_data="notestogglemode_delete")])
    keyboard.append([btn_menu()])

    all_tags = await db_get_note_tags_with_counts(user_id)
    all_tags = [t for t in all_tags if t["count"] > 0]
    if all_tags:
        tag_row = [InlineKeyboardButton("Все" if tag is not None else "• Все", callback_data="open_notes")]
        for t in all_tags:
            label = t["name"] if tag_id != t["id"] else f"• {t['name']}"
            tag_row.append(InlineKeyboardButton(label, callback_data=f"open_notetag_{t['id']}"))
        for i in range(0, len(tag_row), 4):
            keyboard.append(tag_row[i:i + 4])

    msg = await bot.send_message(chat_id=user_id, text=_pad(text), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    register_message(user_id, user_id, msg.message_id)


@register_callback_handler("open_notetag_")
async def cb_open_notetag(query, context, data, user, chat_id, bot):
    tag_id = int(data.split("_")[2])
    await _show_notes(query, tag_id=tag_id)


@register_callback_handler("shownote_")
async def cb_show_note(query, context, data, user, chat_id, bot):
    note_id = int(data.split("_")[1])
    notes = await db_get_notes(user.id)
    note = next((n for n in notes if n["id"] == note_id), None)
    if not note:
        await query.edit_message_text(_pad("❌ Заметка не найдена."))
        return

    content = note["content"]
    tags_str = await tags_display_text(user.id, note_id, "note")

    text = _pad(f"📝 *{md(note['name'])}*\n\n{md(content)}")
    if tags_str:
        text += f"\n\n{tags_str}"

    await query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ Название", callback_data=f"editnotename_{note_id}"),
             InlineKeyboardButton("✏️ Текст", callback_data=f"editnotecontent_{note_id}")],
            [InlineKeyboardButton("◀️ Назад", callback_data="open_notes"), btn_menu()],
        ])
    )




# ─── Note Tags ────────────────────────────────────────────────────────────────

@register_callback_handler("notetags_")
async def cb_notetags(query, context, data, user, chat_id, bot):
    note_id = int(data.split("_")[1])
    from handlers.processors.tag_ui import show_tag_picker
    await show_tag_picker(query, user.id, chat_id, "note", note_id)


@register_callback_handler("notetagedit_")
async def cb_notetagedit(query, context, data, user, chat_id, bot):
    parts = data.split("_")
    note_id = int(parts[1])
    tag_id = int(parts[2])
    from db import db
    tags = await asyncio.to_thread(db.get_note_tags, user.id, note_id)
    existing = {t["id"] for t in tags}
    if tag_id in existing:
        await asyncio.to_thread(db.remove_note_tag, user.id, note_id, tag_id)
    else:
        tag = await asyncio.to_thread(db.get_note_tag, user.id, tag_id)
        if tag:
            await asyncio.to_thread(db.add_note_tag, user.id, note_id, tag["name"])
    from handlers.processors.tag_ui import show_tag_picker
    await show_tag_picker(query, user.id, chat_id, "note", note_id)


@register_callback_handler("notetagnew_")
async def cb_notetagnew(query, context, data, user, chat_id, bot):
    note_id = int(data.split("_")[1])
    start_process(user.id, chat_id, "note_new_tag", {"step": "waiting_tag_name", "note_id": note_id}, query.message.message_id)
    await query.edit_message_text(
        _pad("🏷 *Новый тег*\n\nВведи название тега:"),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
    )


@register_message_handler("note_new_tag")
async def handle_note_new_tag(update, context, proc, state):
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
    note_id = state["note_id"]
    tag_id = await asyncio.to_thread(db.get_or_create_note_tag, user.id, tag_name)
    await asyncio.to_thread(db.add_note_tag, user.id, note_id, tag_name)
    await finish_process(bot, user.id, show_menu=False)
    await show_tag_picker(bot, user.id, chat_id, "note", note_id,
                          message=f"✅ Тег *{md(tag_name)}* добавлен.",
                          is_new_message=True)
