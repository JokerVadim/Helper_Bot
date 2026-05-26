"""Reminder and timer management."""
import logging
from datetime import datetime
from typing import TYPE_CHECKING

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from db import db_delete_reminder, db_get_reminder, db_update_reminder
from handlers.session import reminders, reminder_counter, register_message, _store_memory_reminder, _remove_memory_reminder
from utils import md, _pad
from utils.time_utils import next_repeat_time, _format_reminder_time, _repeat_label, _repeat_icon_full

if TYPE_CHECKING:
    from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


REMINDER_TAG_MAP = {
    "none": "разовое",
    "daily": "ежедневно",
    "weekly": "по дням",
    "monthly": "ежемесячно",
    "yearly": "ежегодно",
    "minutes": "интервал",
    "interval_days": "интервал",
}


def auto_assign_reminder_tags(chat_id: int, rid: int, repeat_type: str):
    """TODO: wrap DB calls in asyncio.to_thread when calling from async contexts"""
    """Автоматически назначить тег напоминанию на основе типа повторения.
    Удаляет fallback-тег 'разное', если он был.
    Использует первичный ключ reminders.id (не rid) для связи reminder_tag_links.
    """
    tag_name = REMINDER_TAG_MAP.get(repeat_type)
    if not tag_name:
        return
    from db import db
    reminder = db.get_reminder(chat_id, rid)
    if not reminder:
        return
    # Используем первичный ключ id, а не rid
    db.add_reminder_tag(chat_id, reminder["id"], tag_name)
    # Удаляем fallback-тег "разное" — он не нужен при наличии конкретного тега
    existing_tags = db.get_reminder_tags(chat_id, reminder["id"])
    for t in existing_tags:
        if t["name"].lower() == "разное":
            db.remove_reminder_tag(chat_id, reminder["id"], t["id"])
            break
    logger.info(f"AUTO TAG: reminder #{rid} (pk={reminder['id']}, chat={chat_id}) -> {tag_name}")


def _cleanup_misc_fallback_tags():
    """Удалить тег 'разное' у напоминаний, у которых уже есть другой тег.
    Нужно для очистки старых записей, где 'разное' остался как fallback.
    """
    from db import db
    rows = db.get_pending_reminders()
    cleaned = 0
    for row in rows:
        if row.get("delivered", 0) or row.get("is_timer", 0):
            continue
        tags = db.get_reminder_tags(row["chat_id"], row["id"])
        # Есть ли теги, кроме "разное"?
        non_misc = [t for t in tags if t["name"].lower() != "разное"]
        if non_misc:
            for t in tags:
                if t["name"].lower() == "разное":
                    db.remove_reminder_tag(row["chat_id"], row["id"], t["id"])
                    cleaned += 1
                    break
    if cleaned:
        logger.info(f"MISC CLEANUP: removed {cleaned} fallback 'разное' tags")


def _cleanup_old_delivered_reminders():
    """Удалить старые доставленные одноразовые напоминания из БД.
    Запускается при старте бота для очистки доставленных напоминаний."""
    from db import db
    rows = db.get_pending_reminders()
    deleted = 0
    for row in rows:
        if not row.get("delivered", 0):
            continue
        repeat_type = row.get("repeat_type") or "none"
        if repeat_type == "none":
            chat_id = row["chat_id"]
            rid = row["rid"]
            db.delete_reminder(chat_id, rid)
            deleted += 1
    if deleted:
        logger.info(f"DELIVERED CLEANUP: deleted {deleted} old delivered one-time reminders")


def tag_existing_reminders():
    """Пробежаться по активным (не доставленным, не таймерам) напоминаниям в БД
    и назначить теги по типу повтора.
    Вызывается при старте бота, чтобы протегировать существующие напоминания.
    """
    from db import db

    # Миграция: переименовать старый тег "в день" → "по дням"
    # (был изменён в REMINDER_TAG_MAP, существующие записи остались со старым именем)
    with db._conn() as con:
        rows_to_rename = con.execute(
            "SELECT id, user_id FROM reminder_tags WHERE name='в день'"
        ).fetchall()
        renamed = 0
        for row in rows_to_rename:
            old_id = int(row["id"])
            user_id = int(row["user_id"])
            # Проверяем, нет ли уже тега "по дням" у этого же пользователя
            existing = con.execute(
                "SELECT id FROM reminder_tags WHERE user_id=? AND name='по дням'",
                (user_id,)
            ).fetchone()
            if existing:
                new_id = int(existing["id"])
                # Удаляем дублирующиеся связи (где напоминание уже имеет новый тег)
                con.execute(
                    "DELETE FROM reminder_tag_links WHERE tag_id=? AND reminder_id IN ("
                    "  SELECT reminder_id FROM reminder_tag_links WHERE tag_id=?"
                    ")",
                    (old_id, new_id)
                )
                # Переносим оставшиеся связи на новый тег
                con.execute(
                    "UPDATE reminder_tag_links SET tag_id=? WHERE tag_id=?",
                    (new_id, old_id)
                )
                # Удаляем старый тег (связей к нему уже нет)
                con.execute("DELETE FROM reminder_tags WHERE id=?", (old_id,))
            else:
                con.execute(
                    "UPDATE reminder_tags SET name='по дням', normalized_name='по дням' WHERE id=?",
                    (old_id,)
                )
            renamed += 1
        if renamed:
            logger.info(f"TAG MIGRATION: renamed {renamed} 'в день' → 'по дням' reminder tags")

    rows = db.get_pending_reminders()
    tagged = 0
    seen = set()
    for row in rows:
        chat_id = row["chat_id"]
        reminder_pk = row["id"]  # первичный ключ
        # Пропускаем доставленные и таймеры — они не видны в списке
        if row.get("delivered", 0):
            continue
        if row.get("is_timer", 0):
            continue
        repeat_type = row.get("repeat_type") or "none"
        tag_name = REMINDER_TAG_MAP.get(repeat_type)
        if not tag_name:
            continue
        key = (chat_id, reminder_pk)
        if key in seen:
            continue
        seen.add(key)
        existing_tags = db.get_reminder_tags(chat_id, reminder_pk)
        if any(t["name"] == tag_name for t in existing_tags):
            continue
        db.add_reminder_tag(chat_id, reminder_pk, tag_name)
        # Удаляем fallback-тег "разное" при наличии конкретного тега
        updated_tags = db.get_reminder_tags(chat_id, reminder_pk)
        for t in updated_tags:
            if t["name"].lower() == "разное":
                db.remove_reminder_tag(chat_id, reminder_pk, t["id"])
                break
        tagged += 1
    logger.info(f"TAGGED EXISTING: {tagged} active reminders tagged at startup")
    # Очищаем старые дубликаты "разное" у уже протегированных напоминаний
    _cleanup_misc_fallback_tags()
    # Удаляем старые доставленные одноразовые напоминания
    _cleanup_old_delivered_reminders()


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
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return datetime.now()


def _row_to_reminder(row: dict, job=None) -> dict:
    return {
        "id": row["rid"],
        "text": row["text"],
        "time": _parse_db_time(row["fire_at"]),
        "job": job,
        "is_timer": bool(row["is_timer"]),
        "repeat_type": row.get("repeat_type") or "none",
        "minutes": row.get("minutes", 0),
        "repeat_days": row.get("repeat_days", ""),
        "delivered": bool(row.get("delivered", 0)),
    }


def _schedule_reminder(job_queue, chat_id: int, rid: int, text: str, fire_at: datetime,
                       is_timer: bool = False, repeat_type: str = "none", minutes: int = 0, repeat_days: str = ""):
    delay = max(1, (fire_at - datetime.now()).total_seconds())
    job = job_queue.run_once(
        reminder_callback, delay, chat_id=chat_id,
        data={"text": text, "id": rid, "repeat_type": repeat_type, "is_timer": is_timer, "minutes": minutes, "repeat_days": repeat_days}
    )
    _store_memory_reminder(chat_id, {
        "id": rid,
        "text": text,
        "time": fire_at,
        "job": job,
        "is_timer": is_timer,
        "repeat_type": repeat_type,
        "minutes": minutes,
        "repeat_days": repeat_days,
        "delivered": False,
    })
    reminder_counter[chat_id] = max(reminder_counter.get(chat_id, 0), rid)
    return job


def _format_reminder_details(r: dict) -> str:
    return _pad(
        f"{_repeat_icon_full(r.get('repeat_type'), r.get('repeat_days', ''))} *Напоминание #{r['id']}*\n\n"
        f"Текст: *{md(_pad(r['text']))}*\n"
        f"Когда: *{md(_format_reminder_time(r))}*\n"
        f"Тип: *{md(_repeat_label(r.get('repeat_type')))}*"
    )


async def show_reminders_ui(query, chat_id: int, bot=None, user_id: int = None, tag_id: int | None = None):
    from telegram import InlineKeyboardMarkup
    from keyboards import btn_menu
    from handlers.processors.reminders import _get_reminder_action_mode

    uid = user_id if user_id else query.from_user.id
    action_mode = _get_reminder_action_mode(uid)

    from db import db_get_reminders_by_tag, db_get_reminder_tags_with_active_counts
    all_tags = await db_get_reminder_tags_with_active_counts(chat_id)

    tag = next((t for t in all_tags if t["id"] == tag_id), None) if tag_id is not None else None

    import logging
    logging.getLogger(__name__).info(
        f"DEBUG show_reminders_ui: tag_id={tag_id!r}, "
        f"all_tags_ids={[t['id'] for t in all_tags]}, "
        f"tag_found={tag['name'] if tag else None}"
    )

    if tag:
        tag_reminders = await db_get_reminders_by_tag(chat_id, tag_id)
        tag_rids = {r["rid"] for r in tag_reminders}
        items = [r for r in reminders.get(chat_id, [])
                 if not r.get("is_timer") and not r.get("delivered") and r["id"] in tag_rids]
    else:
        items = [r for r in reminders.get(chat_id, []) if not r.get("is_timer") and not r.get("delivered")]

    type_order = {"none": 0, "minutes": 1, "interval_days": 1, "daily": 2, "weekly": 3, "monthly": 4, "yearly": 5}
    items.sort(key=lambda r: (type_order.get(r.get("repeat_type", "none"), 9), r["time"]))
    keyboard = []
    for r in items:
        time_str = _format_reminder_time(r)
        if action_mode == "delete":
            callback = f"delrem_{r['id']}"
            prefix = "🗑 "
        elif action_mode == "tags":
            callback = f"remindertags_{r['id']}"
            prefix = "🏷 "
        else:
            callback = f"viewrem_{r['id']}"
            prefix = f"{_repeat_icon_full(r.get('repeat_type'), r.get('repeat_days', ''))} "
        keyboard.append([InlineKeyboardButton(
            f"{prefix}{time_str} — {r['text'][:28]}",
            callback_data=callback
        )])

    delete_lbl = "✅ 🗑 Удалить" if action_mode == "delete" else "🗑 Удалить"
    tags_lbl = "✅ 🏷 Теги" if action_mode == "tags" else "🏷 Теги"
    keyboard.append([
        InlineKeyboardButton("✚ Добавить", callback_data="add_reminder"),
        InlineKeyboardButton(tags_lbl, callback_data="remindertogglemode_tags"),
        InlineKeyboardButton(delete_lbl, callback_data="remindertogglemode_delete"),
    ])
    keyboard.append([btn_menu()])

    # Tag filter buttons (4 per row)
    if all_tags:
        tag_row = [InlineKeyboardButton("Все" if tag is not None else "• Все", callback_data="open_reminders")]
        for t in all_tags:
            label = t['name'] if tag_id != t["id"] else f"• {t['name']}"
            tag_row.append(InlineKeyboardButton(label, callback_data=f"open_remindertag_{t['id']}"))
        if tag_row:
            for i in range(0, len(tag_row), 4):
                keyboard.append(tag_row[i:i + 4])

    if tag:
        text = f"⏰ *Напоминания* / 🏷 *{md(tag['name'])}* ({len(items)})"
    else:
        text = _pad("⏰ *Напоминания:*") if items else _pad("📭 Напоминаний нет")
    if action_mode:
        _mode_labels = {"delete": "🗑 Удалить", "tags": "🏷 Теги"}
        text += f"\n\n*Режим:* ✅ {_mode_labels.get(action_mode, action_mode)}"

    if bot and user_id:
        msg = await bot.send_message(chat_id=user_id, text=text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        register_message(user_id, user_id, msg.message_id)
    else:
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))


async def show_reminder_detail(query, chat_id: int, rid: int):
    from telegram import InlineKeyboardMarkup
    from keyboards import btn_menu

    item = _find_memory_reminder(chat_id, rid)
    if not item:
        row = await db_get_reminder(chat_id, rid)
        item = _row_to_reminder(row) if row else None
    if not item:
        await query.edit_message_text(_pad("❌ Напоминание не найдено."),
                                     reply_markup=InlineKeyboardMarkup([[btn_menu()]]))
        return

    from handlers.processors.tag_ui import tags_display_text
    # Конвертируем rid → PK для работы с тегами
    row_db = await db_get_reminder(chat_id, rid)
    reminder_pk = row_db["id"] if row_db else rid  # fallback на rid если не найдено
    tags_str = await tags_display_text(chat_id, reminder_pk, "reminder")

    keyboard = [
        [
            InlineKeyboardButton("✏️ Название", callback_data=f"editremtext_{rid}"),
            InlineKeyboardButton("✏️ Время", callback_data=f"editremtime_{rid}"),
        ],
        [InlineKeyboardButton("◀️ Назад", callback_data="open_reminders"), btn_menu()],
    ]
    text = _format_reminder_details(item)
    if tags_str:
        text += f"\n\n{tags_str}"
    await query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def show_timers_ui(query, chat_id: int, bot=None, user_id: int = None, delete_mode: bool = False):
    from telegram import InlineKeyboardMarkup
    from keyboards import btn_menu

    items = [r for r in reminders.get(chat_id, []) if r.get("is_timer")]
    keyboard = []
    for r in items:
        remaining = max(0, int((r["time"] - datetime.now()).total_seconds()))
        mins, secs = divmod(remaining, 60)
        remaining_str = f"{mins}м {secs}с" if mins else f"{secs}с"
        # В режиме удаления - показываем корзину, иначе - просто таймер
        prefix = "🗑 " if delete_mode else "⏱ "
        callback = f"deltimer_{r['id']}" if delete_mode else f"viewtimer_{r['id']}"
        keyboard.append([InlineKeyboardButton(
            f"{prefix}{remaining_str} — {r['text'][:25]}",
            callback_data=callback
        )])

    if delete_mode:
        keyboard.append([
            InlineKeyboardButton("✚ Добавить", callback_data="add_timer"),
            InlineKeyboardButton("✅ Готово", callback_data="open_timers"),
        ])
        keyboard.append([btn_menu()])
    else:
        keyboard.append([
            InlineKeyboardButton("✚ Добавить", callback_data="add_timer"),
            InlineKeyboardButton("🗑 Удалить", callback_data="timers_mode_delete"),
        ])
        keyboard.append([btn_menu()])

    text = _pad("⏱ *Таймеры:*") if items else _pad("📭 Таймеров нет")

    # Если передан bot и user_id — отправляем новое сообщение
    if bot and user_id:
        msg = await bot.send_message(chat_id=user_id, text=text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        register_message(user_id, user_id, msg.message_id)
    else:
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

    if is_timer:
        # Для таймера - просто кнопка OK (удаляет сообщение)
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("OK", callback_data=f"reminder_ok_{rid}")]
        ])
    elif repeat_type == "minutes":
        # Для "каждые N минут" - крестик (удалить) и OK (следующее срабатывание через интервал)
        reply_markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("❌", callback_data=f"reminder_del_{rid}"),
                InlineKeyboardButton("OK", callback_data=f"reminder_ok_{rid}"),
            ]
        ])
    else:
        # Для остальных напоминаний - кнопки отложить + OK
        reply_markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("+10м", callback_data=f"snooze_{rid}_10m"),
                InlineKeyboardButton("+1ч", callback_data=f"snooze_{rid}_1h"),
                InlineKeyboardButton("Завтра", callback_data=f"snooze_{rid}_1d"),
            ],
            [InlineKeyboardButton("OK", callback_data=f"reminder_ok_{rid}")],
        ])

    title = "⏱ *Таймер*" if is_timer else "⏰ *Напоминание*"
    try:
        msg = await context.bot.send_message(
            chat_id=chat_id,
            text=_pad(f"{title}\n\n{md(text)}"),
            parse_mode="Markdown",
            reply_markup=reply_markup
        )
        # Регистрируем сообщение напоминания для очистки
        if chat_id:
            register_message(chat_id, chat_id, msg.message_id)
    except Exception as e:
        logger.error(f"Reminder send error: {e}")

    if repeat_type != "none" and not is_timer:
        minutes = job.data.get("minutes", 0)
        repeat_days = job.data.get("repeat_days", "")
        next_time = next_repeat_time(fire_at, repeat_type, minutes=minutes, repeat_days=repeat_days)
        if next_time:
            await db_update_reminder(chat_id, rid, fire_at=next_time, delivered=False)
            _schedule_reminder(context.job_queue, chat_id, rid, text, next_time, False, repeat_type, minutes=minutes)
            return

    if is_timer:
        _remove_memory_reminder(chat_id, rid)
        await db_delete_reminder(chat_id, rid)
        return

    # Одноразовые - помечаем как delivered и удаляем из памяти (чтобы не висело в UI)
    # Само напоминание пока остаётся в БД — нужно для кнопки "Отложить"
    if repeat_type == "none":
        if item:
            _remove_memory_reminder(chat_id, rid)
        await db_update_reminder(chat_id, rid, delivered=True)
        return


