"""Admin callback handlers."""
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from handlers.callbacks.base import domain_handler

logger = logging.getLogger(__name__)


@domain_handler
async def handle_admin_callbacks(query, context, data, user, chat_id, bot):
    if data == "admin_view_errors":
        from config import ADMIN_ID
        from db import db_get_recent_errors, db_mark_errors_read
        from keyboards import btn_menu
        from utils import md, _pad
        if user.id != ADMIN_ID:
            await query.answer("Только для админа", show_alert=True)
            return True
        errors = await db_get_recent_errors(20)
        if not errors:
            await query.edit_message_text(
                _pad("✅ Ошибок нет."),
                reply_markup=InlineKeyboardMarkup([[btn_menu()]])
            )
            return True

        lines = [f"⚠️ *Последние {min(len(errors), 20)} ошибок:*\n"]
        for i, err in enumerate(errors, 1):
            ts = err['created_at'][:19] if err['created_at'] else ''
            uid = str(err['user_id'] or '?')
            text = err.get('message', '?')[:80]
            lines.append(f"{i}. [{ts}] user={uid}")
            lines.append(f"   `{md(text)}`")
        lines.append("\n`/logs N` — посмотреть подробно")
        full = "\n".join(lines)

        keyboard = [
            [InlineKeyboardButton("✅ Отметить прочитанными", callback_data="admin_mark_logs_read")],
            [btn_menu()],
        ]

        try:
            await query.edit_message_text(
                _pad(full), parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception:
            short = "\n".join(lines[:15])
            await query.edit_message_text(
                _pad(short + "\n\n_...остальное в `/logs`_"), parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        return True

    if data == "admin_mark_logs_read":
        from config import ADMIN_ID
        from db import db_mark_errors_read
        from keyboards import show_main_menu
        if user.id != ADMIN_ID:
            await query.answer("Только для админа", show_alert=True)
            return True
        await db_mark_errors_read()
        await query.answer("✅ Ошибки отмечены прочитанными")
        await show_main_menu(bot, user.id, "✅ Ошибки отмечены прочитанными")
        return True

    return False
