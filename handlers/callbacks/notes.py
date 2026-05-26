"""Note callback handlers."""
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from handlers.callbacks.base import domain_handler

logger = logging.getLogger(__name__)


@domain_handler
async def handle_notes_callbacks(query, context, data, user, chat_id, bot):
    if data == "open_notes":
        from handlers.processors.notes import _show_notes
        await _show_notes(query)
        return True

    if data == "add_note":
        from handlers.session import start_process
        from keyboards import btn_cancel
        start_process(user.id, chat_id, "note", {"step": "waiting_name"}, query.message.message_id)
        await query.edit_message_text(
            "📝 *Новая заметка*\n\nВведи название заметки:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        return True

    if data.startswith("editnotename_"):
        from db import db_get_notes
        from handlers.session import start_process
        from keyboards import btn_cancel
        from utils import md, _pad
        note_id = int(data.split("_")[1])
        notes = await db_get_notes(user.id)
        note = next((n for n in notes if n["id"] == note_id), None)
        if not note:
            await query.edit_message_text(_pad("❌ Заметка не найдена."))
            return True
        start_process(user.id, chat_id, "note_edit_name", {"note_id": note_id, "step": "waiting_name", "old_name": note["name"]}, query.message.message_id)
        await query.edit_message_text(
            _pad(f"✏️ *Редактировать название*\n\nТекущее: `{md(note['name'])}`\n\nВведи новое название:"),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        return True

    if data.startswith("editnotecontent_"):
        from db import db_get_notes
        from handlers.session import start_process
        from keyboards import btn_cancel
        from utils import md, _pad
        note_id = int(data.split("_")[1])
        notes = await db_get_notes(user.id)
        note = next((n for n in notes if n["id"] == note_id), None)
        if not note:
            await query.edit_message_text(_pad("❌ Заметка не найдена."))
            return True
        start_process(user.id, chat_id, "note_edit_content", {"note_id": note_id, "step": "waiting_content", "old_content": note["content"]}, query.message.message_id)
        await query.edit_message_text(
            _pad(f"✏️ *Редактировать текст*\n\nТекущий текст:\n```\n{note['content']}\n```\n\nВведи новый текст:"),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        return True

    if data.startswith("delnote_"):
        from db import db_get_notes
        from utils import md, _pad
        from keyboards import btn_menu
        note_id = int(data.split("_")[1])
        notes = await db_get_notes(user.id)
        note = next((n for n in notes if n["id"] == note_id), None)
        if not note:
            await query.answer("❌ Заметка не найдена", show_alert=True)
            return True
        await query.edit_message_text(
            _pad(f"🗑 Удалить заметку *{md(note['name'])}*?"),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Да, удалить", callback_data=f"confirmdelnote_{note_id}")],
                [InlineKeyboardButton("◀️ Назад", callback_data="open_notes"), btn_menu()],
            ])
        )
        return True

    if data.startswith("confirmdelnote_"):
        from db import db_delete_note
        from handlers.processors.notes import _show_notes
        note_id = int(data.split("_")[1])
        await db_delete_note(user.id, note_id)
        await _show_notes(query, "✅ Заметка удалена.")
        return True

    if data.startswith("notestogglemode_"):
        mode = data[16:]
        from handlers.processors.notes import _get_note_action_mode, _set_note_action_mode, _show_notes
        current = _get_note_action_mode(user.id)
        if current == mode:
            _set_note_action_mode(user.id, "")
        else:
            _set_note_action_mode(user.id, mode)
        await _show_notes(query)
        return True

    return False


async def show_note_detail(bot, user_id, note_id, custom_text=None):
    from db import db_get_notes
    from handlers.message_cache import main_menu_messages
    from handlers.processors.tag_ui import tags_display_text
    from handlers.session import register_message
    from keyboards import btn_menu
    from utils import md, _pad
    chat_id = main_menu_messages.get(user_id, user_id)
    notes = await db_get_notes(user_id)
    note = next((n for n in notes if n["id"] == note_id), None)
    if not note:
        msg = await bot.send_message(chat_id=chat_id, text=_pad("❌ Заметка не найдена."))
        register_message(user_id, chat_id, msg.message_id)
        return
    content = note["content"]
    tags_str = await tags_display_text(user_id, note_id, "note")
    text = _pad(f"📝 *{md(note['name'])}*\n\n{md(content)}")
    if tags_str:
        text += f"\n\n{tags_str}"
    if custom_text:
        text = custom_text
    msg = await bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ Название", callback_data=f"editnotename_{note_id}"),
             InlineKeyboardButton("✏️ Текст", callback_data=f"editnotecontent_{note_id}")],
            [InlineKeyboardButton("◀️ Назад", callback_data="open_notes"), btn_menu()],
        ])
    )
    register_message(user_id, chat_id, msg.message_id)
