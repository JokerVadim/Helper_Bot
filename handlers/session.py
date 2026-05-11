"""Process and session state management."""
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

processes: dict[int, dict] = {}
user_messages: dict[int, list[int]] = {}
main_menu_messages: dict[int, int] = {}
reminders: dict[int, list[dict]] = {}
reminder_counter: dict[int, int] = {}


def _store_memory_reminder(chat_id: int, item: dict):
    reminders.setdefault(chat_id, []).append(item)


def _remove_memory_reminder(chat_id: int, rid: int):
    if chat_id in reminders:
        reminders[chat_id] = [r for r in reminders[chat_id] if r["id"] != rid]


def register_message(user_id: int, chat_id: int, message_id: int):
    if user_id in processes:
        messages = processes[user_id].setdefault("messages", [])
        if message_id not in messages:
            messages.append(message_id)
        processes[user_id]["chat_id"] = chat_id
    user_messages.setdefault(user_id, [])
    if message_id not in user_messages[user_id]:
        user_messages[user_id].append(message_id)


def start_process(
    user_id: int,
    chat_id: int,
    process_type: str,
    initial_state: dict | None = None,
    message_id: int | None = None,
):
    processes[user_id] = {
        "type": process_type,
        "chat_id": chat_id,
        "messages": [message_id] if message_id is not None else [],
        "state": initial_state or {},
    }
    logger.info(f"🚀 START PROCESS: user={user_id} type={process_type}")


async def finish_process(bot, user_id: int, show_menu: bool = True, menu_text: str | None = None):
    from keyboards import show_main_menu

    if user_id not in processes:
        if show_menu:
            await show_main_menu(bot, user_id, menu_text)
        return

    proc = processes[user_id]
    chat_id = proc.get("chat_id")
    messages = proc.get("messages", [])

    for msg_id in messages:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=msg_id)
            if main_menu_messages.get(user_id) == msg_id:
                main_menu_messages.pop(user_id, None)
        except Exception as e:
            logger.debug(f"Не удалось удалить {msg_id}: {e}")

    del processes[user_id]

    if show_menu:
        await show_main_menu(bot, user_id, menu_text)

    logger.info(f"🏁 FINISH PROCESS: user={user_id}")
