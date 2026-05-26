"""Shared utilities for callback domain handlers."""

DOMAIN_HANDLERS = []


def domain_handler(func):
    DOMAIN_HANDLERS.append(func)
    return func


async def _delete_ok_messages(bot, chat_id, *message_ids):
    ids = [mid for mid in message_ids if mid]
    if not ids:
        return
    if len(ids) > 1:
        try:
            await bot.delete_messages(chat_id=chat_id, message_ids=ids)
            return
        except Exception:
            pass
    for mid in ids:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=mid)
        except Exception:
            pass
