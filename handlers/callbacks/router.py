"""Callback button handler with domain handler dispatch."""
import logging

from handlers.callbacks.base import DOMAIN_HANDLERS

# Import domain modules to register their handlers via @domain_handler decorator
from handlers.callbacks import admin  # noqa: F401
from handlers.callbacks import cards  # noqa: F401
from handlers.callbacks import documents  # noqa: F401
from handlers.callbacks import lists  # noqa: F401
from handlers.callbacks import locations  # noqa: F401
from handlers.callbacks import misc  # noqa: F401
from handlers.callbacks import notes  # noqa: F401
from handlers.callbacks import reminders  # noqa: F401

logger = logging.getLogger(__name__)


async def button_handler(update, context):
    query = update.callback_query
    await query.answer()
    data = query.data
    user = query.from_user
    chat_id = query.message.chat_id
    bot = context.bot

    from utils import is_authorized, _pad
    if not is_authorized(user.id):
        try:
            await query.edit_message_text(_pad("❌ Доступ запрещён. Обратитесь к администратору."))
        except Exception:
            msg = await bot.send_message(chat_id=chat_id, text=_pad("❌ Доступ запрещён. Обратитесь к администратору."))
            from handlers.session import register_message
            register_message(user.id, chat_id, msg.message_id)
        return

    from handlers.session import register_message
    register_message(user.id, chat_id, query.message.message_id)

    for handler in DOMAIN_HANDLERS:
        if await handler(query, context, data, user, chat_id, bot):
            return

    from handlers.processors import get_callback_handler
    handler_func, pattern = get_callback_handler(data)
    if handler_func:
        await handler_func(query, context, data, user, chat_id, bot)
        return

    logger.warning(f"Unhandled callback: {data}")
