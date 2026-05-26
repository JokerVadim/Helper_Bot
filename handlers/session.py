"""Process and session state management."""
import logging
import threading

logger = logging.getLogger(__name__)

# ─── Блокировки для защиты shared state ───────────────────────────────────────
# threading.Lock для синхронных функций, asyncio.Lock для async-функций.
_sh_lock = threading.Lock()

processes: dict[int, dict] = {}
user_messages: dict[int, list[int]] = {}
main_menu_messages: dict[int, int] = {}
reminders: dict[int, list[dict]] = {}
reminder_counter: dict[int, int] = {}
pin_unlocked: dict[int, float] = {}  # user_id -> timestamp of last unlock
pin_attempts: dict[int, dict] = {}  # user_id -> {"count": int, "locked_until": float}


def _store_memory_reminder(chat_id: int, item: dict):
    with _sh_lock:
        if chat_id in reminders:
            reminders[chat_id] = [r for r in reminders[chat_id] if r["id"] != item["id"]]
        reminders.setdefault(chat_id, []).append(item)


def _remove_memory_reminder(chat_id: int, rid: int):
    with _sh_lock:
        if chat_id in reminders:
            reminders[chat_id] = [r for r in reminders[chat_id] if r["id"] != rid]


def is_pin_unlocked(user_id: int) -> bool:
    """Check if PIN is currently unlocked for this user (15 min session)."""
    import time
    from config import PIN_SESSION_MINUTES
    if user_id not in pin_unlocked:
        return False
    elapsed = time.time() - pin_unlocked[user_id]
    return elapsed < PIN_SESSION_MINUTES * 60


def unlock_pin(user_id: int):
    import time
    pin_unlocked[user_id] = time.time()


def lock_pin(user_id: int):
    pin_unlocked.pop(user_id, None)


def is_pin_locked(user_id: int) -> bool:
    """Check if PIN is currently locked due to too many failed attempts."""
    import time
    if user_id not in pin_attempts:
        return False
    locked_until = pin_attempts[user_id].get("locked_until", 0)
    if time.time() < locked_until:
        return True
    # Lock expired — reset
    pin_attempts.pop(user_id, None)
    return False


def record_pin_attempt(user_id: int, success: bool):
    """Record a PIN attempt. If failed too many times, lock."""
    import time
    from config import PIN_LOCKOUT_ATTEMPTS, PIN_LOCKOUT_SECONDS
    if success:
        pin_attempts.pop(user_id, None)
        return
    data = pin_attempts.setdefault(user_id, {"count": 0, "locked_until": 0})
    data["count"] += 1
    if data["count"] >= PIN_LOCKOUT_ATTEMPTS:
        data["locked_until"] = time.time() + PIN_LOCKOUT_SECONDS
        logger.warning(f"PIN locked for user {user_id} for {PIN_LOCKOUT_SECONDS}s")


def register_message(user_id: int, chat_id: int, message_id: int):
    with _sh_lock:
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
    with _sh_lock:
        processes[user_id] = {
            "type": process_type,
            "chat_id": chat_id,
            "messages": [message_id] if message_id is not None else [],
            "state": initial_state or {},
        }
    logger.info(f"🚀 START PROCESS: user={user_id} type={process_type}")


async def finish_process(bot, user_id: int, show_menu: bool = True, menu_text: str | None = None):
    from keyboards import show_main_menu

    with _sh_lock:
        proc = processes.pop(user_id, None)
        if proc:
            chat_id = proc.get("chat_id")
            messages = proc.get("messages", [])
    if not proc:
        if show_menu:
            await show_main_menu(bot, user_id, menu_text)
        return

    for msg_id in messages:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=msg_id)
            with _sh_lock:
                if main_menu_messages.get(user_id) == msg_id:
                    main_menu_messages.pop(user_id, None)
        except Exception as e:
            logger.debug(f"Не удалось удалить {msg_id}: {e}")

    if show_menu:
        await show_main_menu(bot, user_id, menu_text)

    logger.info(f"🏁 FINISH PROCESS: user={user_id}")


async def cleanup_all_messages(bot, user_id: int, chat_id: int):
    """Удалить все сообщения бота для пользователя."""
    with _sh_lock:
        msg_ids = list(user_messages.get(user_id, []))
        mm_id = main_menu_messages.get(user_id)
        proc = processes.pop(user_id, None)
        proc_msg_ids = list(proc.get("messages", [])) if proc else []

    # Удаляем зарегистрированные сообщения
    deleted = []
    for msg_id in msg_ids:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=msg_id)
            deleted.append(msg_id)
        except Exception:
            pass
    with _sh_lock:
        if user_id in user_messages:
            user_messages[user_id] = [m for m in user_messages[user_id] if m not in deleted]

    # Удаляем главное меню
    if mm_id:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=mm_id)
        except Exception:
            pass
        with _sh_lock:
            if main_menu_messages.get(user_id) == mm_id:
                main_menu_messages.pop(user_id, None)

    # Удаляем сообщения процесса
    for msg_id in proc_msg_ids:
        if msg_id not in deleted:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=msg_id)
            except Exception:
                pass
