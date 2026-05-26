"""Health/status helpers for /status."""
import os
from datetime import datetime, timedelta
from pathlib import Path

import ai
import db as db_module
from db import (
    db_count_lists,
    db_count_users,
    db_get_pending_reminders,
    db_get_recent_errors,
    db_get_reminder_counts,
    db_get_unread_errors_count,
)
from utils import md


def _flag(value: bool) -> str:
    return "✅" if value else "⚠️"


def _format_size(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    if size >= 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size} B"


def latest_backup(backup_dir: str = "backups") -> dict | None:
    root = Path(backup_dir)
    if not root.exists():
        return None
    backups = [p for p in root.glob("*.db") if p.is_file()]
    if not backups:
        return None
    latest = max(backups, key=lambda p: p.stat().st_mtime)
    stat = latest.stat()
    return {
        "name": latest.name,
        "mtime": datetime.fromtimestamp(stat.st_mtime),
        "size": stat.st_size,
    }


def _count_errors_last_day(errors: list[dict], now: datetime | None = None) -> int:
    now = now or datetime.now()
    cutoff = now - timedelta(days=1)
    count = 0
    for error in errors:
        created_at = error.get("created_at")
        if not created_at:
            continue
        try:
            dt = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        if dt >= cutoff:
            count += 1
    return count


async def build_status_text(active_process: str = "нет") -> str:
    db_ok = True
    db_error = ""
    try:
        counts = await db_get_reminder_counts()
        list_count = await db_count_lists()
        user_count = await db_count_users()
        pending_reminders = await db_get_pending_reminders()
        unread_errors = await db_get_unread_errors_count()
        recent_errors = await db_get_recent_errors(100)
    except Exception as exc:
        db_ok = False
        db_error = str(exc)[:120]
        counts = {}
        list_count = 0
        user_count = 0
        pending_reminders = []
        unread_errors = 0
        recent_errors = []

    active_reminders = sum(
        1 for row in pending_reminders
        if not row.get("delivered", 0) and not row.get("is_timer", 0)
    )
    active_timers = sum(
        1 for row in pending_reminders
        if not row.get("delivered", 0) and row.get("is_timer", 0)
    )

    backup = latest_backup()
    backup_text = "нет" if not backup else (
        f"{backup['mtime'].strftime('%d.%m %H:%M')} ({_format_size(backup['size'])})"
    )

    db_exists = os.path.exists(db_module.DB_PATH)
    db_size = _format_size(os.path.getsize(db_module.DB_PATH)) if db_exists else "нет файла"
    errors_last_day = _count_errors_last_day(recent_errors)

    db_line = f"{_flag(db_ok)} БД: `{db_module.DB_PATH}` ({db_size})"
    if not db_ok:
        db_line += f"\nОшибка БД: `{md(db_error)}`"

    return (
        "✅ *Статус бота*\n\n"
        f"{db_line}\n"
        f"{_flag(ai.ai_ready.get('groq', False))} Groq: *{'OK' if ai.ai_ready.get('groq') else 'недоступен'}*\n"
        f"{_flag(ai.ai_ready.get('tavily', False))} Tavily: *{'OK' if ai.ai_ready.get('tavily') else 'недоступен'}*\n"
        f"{_flag(ai.ai_ready.get('fallback', False))} Fallback AI: *{'OK' if ai.ai_ready.get('fallback') else 'выключен'}*\n\n"
        f"Напоминания: *{active_reminders}* активных, *{active_timers}* таймеров\n"
        f"• одноразовые: *{counts.get('once', 0)}*\n"
        f"• сработавшие: *{counts.get('delivered', 0)}*\n"
        f"• ежедневные: *{counts.get('daily', 0)}*\n"
        f"• ежемесячные: *{counts.get('monthly', 0)}*\n"
        f"• ежегодные: *{counts.get('yearly', 0)}*\n\n"
        f"Списки: *{list_count}*\n"
        f"Пользователи: *{user_count}*\n"
        f"Ошибки: *{errors_last_day}* за 24ч, непрочитанных: *{unread_errors}*\n"
        f"Последний backup: *{backup_text}*\n"
        f"Текущий процесс: `{md(active_process)}`"
    )
