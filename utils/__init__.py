"""Utils package."""
import asyncio

# Хранилище фоновых задач — предотвращает уничтожение задач сборщиком мусора
_background_tasks: set = set()


def fire_and_forget(coro) -> asyncio.Task:
    """Создать фоновую задачу с сохранением ссылки для защиты от GC."""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


def md(text) -> str:
    from telegram.helpers import escape_markdown
    return escape_markdown(str(text), version=1)


def _pad(text: str, width: int = 32) -> str:
    """Дополнить строку справа до нужной ширины."""
    return text + "\u3164" * max(1, width - len(text))


def is_authorized(user_id: int) -> bool:
    """Проверить, имеет ли пользователь доступ к боту.
    
    Если lockdown выключен (по умолчанию) — доступ есть у всех.
    Если lockdown включён — только админ, ALLOWED_IDS и белый список.
    Администратор (ADMIN_ID из .env) имеет доступ всегда.
    """
    from config import ADMIN_ID, ALLOWED_IDS
    
    # Админ всегда имеет доступ
    if ADMIN_ID is not None and user_id == ADMIN_ID:
        return True
    
    # Проверяем режим lockdown
    from db import db
    if not db.get_lockdown():
        # Режим ограничения выключен — доступ есть у всех
        return True
    
    # Режим ограничения включён — проверяем белый список
    if user_id in ALLOWED_IDS:
        return True
    return db.is_user_allowed(user_id)


from utils.time_utils import (  # noqa: F401
    parse_duration_seconds,
    next_repeat_time,
    parse_reminder_time_arg,
    parse_clock,
    next_daily_at,
    next_monthly_at,
    next_yearly_at,
    describe_when,
    parse_time_arg,
    _repeat_label,
    _repeat_icon,
    _repeat_icon_full,
    _format_reminder_time,
)
