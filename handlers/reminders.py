"""Reminder and timer management."""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from db import db_save_reminder, db_delete_reminder, db_get_reminder, db_update_reminder
from handlers.session import reminders, reminder_counter, _store_memory_reminder, _remove_memory_reminder
from utils.time_utils import next_repeat_time, _format_reminder_time, _repeat_label, _repeat_icon

if TYPE_CHECKING:
    from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


def next_reminder_id(chat_id: int) -> int:
    reminder_counter[chat_id] = reminder_counter.get(chat_id, 0) + 1
    return reminder_counter[chat_id]


def _find_memory_reminder(chat_id: int, rid: int):
    return next((r for r in reminders.get(chat_id, []) if r["id"] == rid), None)


def _cancel_reminder_job(chat_id: int, rid: int):
    target = _find_memory_reminder(chat_id, rid)
    if target and target.get("job"):
        target["job"].schedule_removal()


def _parse_db_time(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")


def _row_to_reminder(row: dict, job=None) -> dict:
    return {
        "id": row["rid"],
        "text": row["text"],
        "time": _parse_db_time(row["fire_at"]),
        "job": job,
        "is_timer": bool(row["is_timer"]),
        "repeat_type": row.get("repeat_type") or "none",
        "delivered": bool(row.get("delivered", 0)),
    }


def _schedule_reminder(job_queue, chat_id: int, rid: int, text: str, fire_at: datetime,
                       is_timer: bool = False, repeat_type: str = "none"):
    delay = max(1, (fire_at - datetime.now()).total_seconds())
    job = job_queue.run_once(
        reminder_callback, delay, chat_id=chat_id,
        data={"text": text, "id": rid, "repeat_type": repeat_type, "is_timer": is_timer}
    )
    _store_memory_reminder(chat_id, {
        "id": rid,
        "text": text,
        "time": fire_at,
        "job": job,
        "is_timer": is_timer,
        "repeat_type": repeat_type,
        "delivered": False,
    })
    reminder_counter[chat_id] = max(reminder_counter.get(chat_id, 0), rid)
    return job


def _format_reminder_details(r: dict) -> str:
    from bot import md
    return (
        f"{_repeat_icon(r.get('repeat_type'))} *Напоминание #{r['id']}*\n\n"
        f"Текст: *{md(r['text'])}*\n"
        f"Когда: *{md(_format_reminder_time(r))}*\n"
        f"Тип: *{md(_repeat_label(r.get('repeat_type')))}*"
    )


async def show_reminders_ui(query, chat_id: int):
    from telegram import InlineKeyboardMarkup

    items = [r for r in reminders.get(chat_id, []) if not r.get("is_timer")]
    items.sort(key=lambda r: r["time"])
    keyboard = []
    for r in items:
        time_str = _format_reminder_time(r)
        keyboard.append([InlineKeyboardButton(
            f"{_repeat_icon(r.get('repeat_type'))} {time_str} — {r['text'][:28]}",
            callback_data=f"viewrem_{r['id']}"
        )])
    keyboard.append([InlineKeyboardButton("➕ Добавить", callback_data="add_reminder")])
    keyboard.append([InlineKeyboardButton("🏠 Меню", callback_data="go_menu")])
    text = "⏰ *Напоминания:*\n_нажми чтобы открыть_" if items else "📭 Напоминаний нет"
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))


async def show_reminder_detail(query, chat_id: int, rid: int):
    from telegram import InlineKeyboardMarkup
    from keyboards import btn_menu

    item = _find_memory_reminder(chat_id, rid)
    if not item:
        row = await asyncio.to_thread(db_get_reminder, chat_id, rid)
        item = _row_to_reminder(row) if row else None
    if not item:
        await query.edit_message_text("❌ Напоминание не найдено.",
                                     reply_markup=InlineKeyboardMarkup([[btn_menu()]]))
        return

    keyboard = [
        [
            InlineKeyboardButton("✏️ Текст", callback_data=f"editremtext_{rid}"),
            InlineKeyboardButton("🕒 Время", callback_data=f"editremtime_{rid}"),
        ],
        [InlineKeyboardButton("🔁 Повтор", callback_data=f"editremrepeat_{rid}")],
        [
            InlineKeyboardButton("+10м", callback_data=f"snooze_{rid}_10m"),
            InlineKeyboardButton("+1ч", callback_data=f"snooze_{rid}_1h"),
            InlineKeyboardButton("Завтра", callback_data=f"snooze_{rid}_1d"),
        ],
        [InlineKeyboardButton("🗑 Удалить", callback_data=f"delrem_{rid}")],
        [InlineKeyboardButton("◀️ Назад", callback_data="open_reminders"), btn_menu()],
    ]
    await query.edit_message_text(
        _format_reminder_details(item),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def show_timers_ui(query, chat_id: int):
    from telegram import InlineKeyboardMarkup
    from keyboards import btn_menu

    items = [r for r in reminders.get(chat_id, []) if r.get("is_timer")]
    keyboard = []
    for r in items:
        remaining = max(0, int((r["time"] - datetime.now()).total_seconds()))
        mins, secs = divmod(remaining, 60)
        remaining_str = f"{mins}м {secs}с" if mins else f"{secs}с"
        keyboard.append([InlineKeyboardButton(
            f"⏱ {remaining_str} — {r['text'][:28]}",
            callback_data=f"deltimer_{r['id']}"
        )])
    keyboard.append([InlineKeyboardButton("➕ Добавить", callback_data="add_timer")])
    keyboard.append([btn_menu()])
    text = "⏱ *Таймеры:*\n_нажми чтобы удалить_" if items else "📭 Таймеров нет"
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))


async def reminder_callback(context: "ContextTypes.DEFAULT_TYPE"):
    job = context.job
    chat_id = job.chat_id
    text = job.data["text"]
    rid  = job.data["id"]
    repeat_type = job.data.get("repeat_type", "none")
    is_timer = bool(job.data.get("is_timer", False))
    item = _find_memory_reminder(chat_id, rid)
    fire_at = item["time"] if item else datetime.now()
    reply_markup = None if is_timer else InlineKeyboardMarkup([
        [
            InlineKeyboardButton("+10м", callback_data=f"snooze_{rid}_10m"),
            InlineKeyboardButton("+1ч", callback_data=f"snooze_{rid}_1h"),
            InlineKeyboardButton("Завтра", callback_data=f"snooze_{rid}_1d"),
        ],
        [InlineKeyboardButton("Открыть", callback_data=f"viewrem_{rid}")],
    ])
    title = "⏱ *Таймер*" if is_timer else "⏰ *Напоминание*"
    try:
        from bot import md
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"{title}\n\n{md(text)}",
            parse_mode="Markdown",
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Reminder send error: {e}")

    if repeat_type != "none" and not is_timer:
        next_time = next_repeat_time(fire_at, repeat_type)
        if next_time:
            await asyncio.to_thread(db_update_reminder, chat_id, rid, fire_at=next_time, delivered=False)
            _schedule_reminder(context.job_queue, chat_id, rid, text, next_time, False, repeat_type)
            return

    if is_timer:
        _remove_memory_reminder(chat_id, rid)
        await asyncio.to_thread(db_delete_reminder, chat_id, rid)
        return

    if item:
        item["delivered"] = True
        item["job"] = None
    await asyncio.to_thread(db_update_reminder, chat_id, rid, delivered=True)
