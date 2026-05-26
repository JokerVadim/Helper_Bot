"""Card callback handlers."""
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from handlers.callbacks.base import domain_handler

logger = logging.getLogger(__name__)


@domain_handler
async def handle_cards_callbacks(query, context, data, user, chat_id, bot):
    if data == "open_cards":
        from handlers.processors.cards import _show_cards
        await _show_cards(query)
        return True

    if data == "add_card":
        from handlers.session import start_process
        from keyboards import btn_cancel
        start_process(user.id, chat_id, "card", {"step": "waiting_name"}, query.message.message_id)
        await query.edit_message_text(
            "💳 *Добавить карту*\n\nВведи название карты (например: Моя карта, Карта жены):",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        return True

    if data.startswith("showcard_"):
        import asyncio
        from db import db_get_cards
        from handlers.processors.cards import _set_card_preview, _auto_hide_preview, _show_cards_content, _card_preview, _card_preview_task
        card_id = int(data.split("_")[1])
        cards = await db_get_cards(user.id)
        card = next((c for c in cards if c["id"] == card_id), None)
        if not card:
            await query.answer("❌ Карта не найдена", show_alert=True)
            return True

        current = _card_preview.get(user.id)
        if current and current["name"] == card["name"] and current["number"] == card["number"]:
            _set_card_preview(user.id, None)
            if _card_preview_task.get(user.id):
                _card_preview_task[user.id].cancel()
                _card_preview_task[user.id] = None
        else:
            _set_card_preview(user.id, card)
            if _card_preview_task.get(user.id):
                _card_preview_task[user.id].cancel()
            _card_preview_task[user.id] = asyncio.create_task(
                _auto_hide_preview(user.id, chat_id, query.message.message_id, bot)
            )

        await _show_cards_content(query)
        return True

    if data.startswith("delcard_"):
        from db import db_get_cards
        from utils import md, _pad
        from keyboards import btn_menu
        card_id = int(data.split("_")[1])
        cards = await db_get_cards(user.id)
        card = next((c for c in cards if c["id"] == card_id), None)
        if not card:
            await query.edit_message_text("❌ Карта не найдена.")
            return True

        await query.edit_message_text(
            _pad(f"🗑 Удалить карту *{md(card['name'])}*?"),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Да, удалить", callback_data=f"confirmdelcard_{card_id}")],
                [InlineKeyboardButton("◀️ Назад", callback_data="open_cards"), btn_menu()],
            ])
        )
        return True

    if data.startswith("confirmdelcard_"):
        from db import db_delete_card
        from handlers.processors.cards import _show_cards
        card_id = int(data.split("_")[1])
        await db_delete_card(user.id, card_id)
        await _show_cards(query, "✅ Карта удалена.")
        return True

    if data.startswith("cardstogglemode_"):
        mode = data[16:]
        from handlers.processors.cards import _get_card_action_mode, _set_card_action_mode, _show_cards
        current = _get_card_action_mode(user.id)
        if current == mode:
            _set_card_action_mode(user.id, "")
        else:
            _set_card_action_mode(user.id, mode)
        await _show_cards(query)
        return True

    if data.startswith("editcardname_"):
        from db import db_get_cards
        from handlers.session import start_process
        from keyboards import btn_cancel
        from utils import md, _pad
        card_id = int(data.split("_")[1])
        cards = await db_get_cards(user.id)
        card = next((c for c in cards if c["id"] == card_id), None)
        if not card:
            await query.edit_message_text(_pad("❌ Карта не найдена."))
            return True
        start_process(user.id, chat_id, "card_edit_name", {"card_id": card_id, "step": "waiting_name", "old_name": card["name"]}, query.message.message_id)
        await query.edit_message_text(
            _pad(f"✏️ *Редактировать название*\n\nТекущее: `{md(card['name'])}`\n\nВведи новое название:"),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        return True

    if data.startswith("editcardnum_"):
        from db import db_get_cards
        from handlers.session import start_process
        from keyboards import btn_cancel
        from utils import md, _pad
        card_id = int(data.split("_")[1])
        cards = await db_get_cards(user.id)
        card = next((c for c in cards if c["id"] == card_id), None)
        if not card:
            await query.edit_message_text(_pad("❌ Карта не найдена."))
            return True
        start_process(user.id, chat_id, "card_edit_number", {"card_id": card_id, "step": "waiting_number"}, query.message.message_id)
        await query.edit_message_text(
            _pad(f"✏️ *Редактировать номер*\n\nТекущий номер: `{card['number']}`\n\nВведи новый номер (только цифры):"),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        return True

    return False
