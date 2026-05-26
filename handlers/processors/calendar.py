"""Calendar view — единый календарь напоминаний и дней рождений."""
import calendar
from datetime import datetime, date
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest

from keyboards import btn_menu, btn_cancel
from handlers.session import reminders, start_process
from handlers.processors.birthdays import _calc_age
from handlers.processors import register_callback_handler
from utils.time_utils import WEEKDAY_NAMES, _repeat_icon_full, _format_reminder_time
from utils import md, _pad

MONTH_NAMES_GEN = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля",
    5: "мая", 6: "июня", 7: "июля", 8: "августа",
    9: "сентября", 10: "октября", 11: "ноября", 12: "декабря",
}

MONTH_NAMES_NOM = {
    1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель",
    5: "Май", 6: "Июнь", 7: "Июль", 8: "Август",
    9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь",
}


async def _get_events_for_date(user_id: int, year: int, month: int, day: int, all_bdays: list[dict]) -> list[dict]:
    """Get reminders and birthdays for a specific date."""
    target_date = date(year, month, day)
    events = []

    for r in reminders.get(user_id, []):
        if r.get("is_timer"):
            continue
        r_time = r["time"]
        r_date = r_time.date() if hasattr(r_time, 'date') else r_time
        repeat_type = r.get("repeat_type", "none")
        delivered = r.get("delivered", False)

        if delivered:
            continue

        # ── Одноразовые — только на точную дату ──
        if repeat_type == "none":
            if r_date.year != year or r_date.month != month:
                continue
            if r_date == target_date:
                events.append({"type": "reminder", "data": r})
            continue

        # ── Повторяющиеся — не показывать, если созданы позже ──
        if r_date > target_date:
            continue

        if repeat_type in ("daily", "minutes", "interval_days"):
            events.append({"type": "reminder", "data": r})
        elif repeat_type == "weekly":
            repeat_days = r.get("repeat_days", "")
            if repeat_days:
                days_set = {int(d) for d in repeat_days.split(",") if d.strip().isdigit()}
                if target_date.weekday() in days_set:
                    events.append({"type": "reminder", "data": r})
        elif repeat_type == "monthly":
            if r_date.day == day:
                events.append({"type": "reminder", "data": r})
        elif repeat_type == "yearly":
            if r_date.day == day and r_date.month == month:
                events.append({"type": "reminder", "data": r})

    for b in all_bdays:
        parts = b["birth_date"].split(".")
        if len(parts) >= 2:
            b_day, b_month = int(parts[0]), int(parts[1])
            if b_day == target_date.day and b_month == target_date.month:
                events.append({"type": "birthday", "data": b})

    events.sort(key=lambda e: e["data"].get("time", datetime.max) if e["type"] == "reminder" else datetime.max)
    return events


async def _build_days_with_events(user_id: int, year: int, month: int, all_bdays: list[dict]) -> dict[int, str]:
    """Return dict of day → emoji for days that have events."""
    days_with_events: dict[int, str] = {}
    for r in reminders.get(user_id, []):
        if r.get("is_timer"):
            continue
        r_date = r["time"].date() if hasattr(r["time"], 'date') else r["time"]
        repeat_type = r.get("repeat_type", "none")
        delivered = r.get("delivered", False)

        if delivered:
            continue

        # ── Одноразовые — только в месяц создания ──
        if repeat_type == "none":
            if r_date.year != year or r_date.month != month:
                continue
            days_with_events.setdefault(r_date.day, "🔸")
            continue

        # ── Повторяющиеся — проверяем, что созданы не позже этого месяца ──
        last_day = calendar.monthrange(year, month)[1]
        current_month_end = date(year, month, last_day)
        if r_date > current_month_end:
            continue

        if repeat_type == "daily":
            start_day = r_date.day if r_date.year == year and r_date.month == month else 1
            for d in range(start_day, last_day + 1):
                days_with_events.setdefault(d, "🔸")
        elif repeat_type == "weekly":
            repeat_days = r.get("repeat_days", "")
            if repeat_days:
                days_set = {int(d) for d in repeat_days.split(",") if d.strip().isdigit()}
                for d in range(1, last_day + 1):
                    if date(year, month, d).weekday() in days_set:
                        days_with_events.setdefault(d, "🔸")
        elif repeat_type == "monthly":
            if 1 <= r_date.day <= last_day:
                days_with_events.setdefault(r_date.day, "🔸")
        elif repeat_type == "yearly":
            if r_date.month == month and 1 <= r_date.day <= last_day:
                days_with_events.setdefault(r_date.day, "🔸")
        elif repeat_type in ("minutes", "interval_days"):
            for d in range(1, last_day + 1):
                days_with_events.setdefault(d, "🔸")

    for b in all_bdays:
        parts = b["birth_date"].split(".")
        if len(parts) >= 2:
            b_day, b_month = int(parts[0]), int(parts[1])
            if b_month == month:
                _, last_day = calendar.monthrange(year, month)
                if 1 <= b_day <= last_day:
                    days_with_events[b_day] = "🎂"  # 🎂 приоритетнее 🔸

    # ── Убираем маркеры с прошедших дней ──
    today = date.today()
    return {d: emoji for d, emoji in days_with_events.items() if date(year, month, d) >= today}


async def _show_calendar(query, user_id: int, year: int, month: int, selected_day: Optional[int] = None, custom_text: str = None):
    """Показать календарь."""
    from db import db_get_birthdays
    all_bdays = await db_get_birthdays( user_id)
    today = date.today()
    cal = calendar.monthcalendar(year, month)

    days_with_events = await _build_days_with_events(user_id, year, month, all_bdays)

    today_marker = (year == today.year and month == today.month)

    keyboard = []

    # Header row
    header_row = []
    for wd_name in WEEKDAY_NAMES:
        header_row.append(InlineKeyboardButton(wd_name, callback_data="noop"))
    keyboard.append(header_row)

    # Day grid
    for week in cal:
        row = []
        for d in week:
            if d == 0:
                row.append(InlineKeyboardButton(" ", callback_data="noop"))
            else:
                icon = days_with_events.get(d, "")
                is_today = today_marker and d == today.day
                if is_today:
                    if icon:
                        label = f"{icon}{d}"
                    else:
                        label = f"{d}❗️"
                elif icon:
                    label = f"{icon}{d}"
                else:
                    label = str(d)
                row.append(InlineKeyboardButton(label, callback_data=f"calday_{year}_{month}_{d}"))
        keyboard.append(row)

    # Navigation row
    prev_month = month - 1
    prev_year = year
    if prev_month < 1:
        prev_month = 12
        prev_year -= 1
    next_month = month + 1
    next_year = year
    if next_month > 12:
        next_month = 1
        next_year += 1

    # Action buttons when a day is selected
    if selected_day:
        keyboard.append([
            InlineKeyboardButton("⏰ Напоминание", callback_data=f"cal_set_remind_{year}_{month}_{selected_day}"),
            InlineKeyboardButton("🎂 День рождения", callback_data=f"cal_set_bday_{year}_{month}_{selected_day}"),
        ])

    keyboard.append([
        InlineKeyboardButton("◀️", callback_data=f"calnav_{prev_year}_{prev_month}"),
        InlineKeyboardButton(f"{MONTH_NAMES_NOM[month]} {year}", callback_data="noop"),
        InlineKeyboardButton("▶️", callback_data=f"calnav_{next_year}_{next_month}"),
    ])
    keyboard.append([InlineKeyboardButton(f"📅 {today.day} {MONTH_NAMES_GEN[today.month]}", callback_data=f"calnav_{today.year}_{today.month}"), btn_menu()])

    # Selected day events
    text = f"📅 *{MONTH_NAMES_NOM[month]} {year}*"
    if selected_day:
        day_events = await _get_events_for_date(user_id, year, month, selected_day, all_bdays)
        sel_date = date(year, month, selected_day)
        is_today = (sel_date == today)
        day_label = "📅 *Сегодня*" if is_today else f"📅 *{selected_day} {MONTH_NAMES_GEN[month]}*"
        text += f"\n\n{day_label}"

        if not day_events:
            text += "\n\nНет событий."
        else:
            for ev in day_events:
                if ev["type"] == "reminder":
                    r = ev["data"]
                    time_str = _format_reminder_time(r)
                    icon = _repeat_icon_full(r.get("repeat_type", "none"), r.get("repeat_days", ""))
                    text += f"\n⏰ {icon} {time_str} — {md(r['text'][:60])}"
                elif ev["type"] == "birthday":
                    b = ev["data"]
                    age_str = ""
                    age = _calc_age(b["birth_date"])
                    if age is not None:
                        age_str = f" ({age})"
                    text += f"\n🎂 *{md(b['name'])}*{age_str}"
    elif custom_text:
        text += f"\n\n{custom_text}"

    await _edit_or_ignore(query, text, keyboard)


async def _edit_or_ignore(query, text: str, keyboard: list):
    """Edit message text, ignoring 'Message is not modified' errors."""
    try:
        await query.edit_message_text(_pad(text), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    except BadRequest as e:
        if "Message is not modified" not in str(e):
            raise


@register_callback_handler("open_calendar")
async def cb_open_calendar(query, context, data, user, chat_id, bot):
    """Открыть календарь на текущем месяце."""
    today = date.today()
    await _show_calendar(query, user.id, today.year, today.month)


@register_callback_handler("calday_")
async def cb_calendar_day(query, context, data, user, chat_id, bot):
    """Нажатие на день в календаре."""
    parts = data.split("_")
    year = int(parts[1])
    month = int(parts[2])
    day = int(parts[3])
    await _show_calendar(query, user.id, year, month, selected_day=day)


@register_callback_handler("calnav_")
async def cb_calendar_nav(query, context, data, user, chat_id, bot):
    """Навигация по месяцам."""
    parts = data.split("_")
    year = int(parts[1])
    month = int(parts[2])
    await _show_calendar(query, user.id, year, month)


@register_callback_handler("cal_set_remind_")
async def cb_calendar_set_remind(query, context, data, user, chat_id, bot):
    """Создать напоминание на выбранный день из календаря."""
    from datetime import date
    parts = data.split("_")
    year = int(parts[3])
    month = int(parts[4])
    day = int(parts[5])

    start_process(user.id, chat_id, "reminder_from_calendar", {
        "step": "waiting_repeat",
        "prefilled_date": date(year, month, day),
    }, query.message.message_id)

    await query.edit_message_text(
        _pad(f"⏰ *Напоминание на {day}.{month:02d}.{year}*\n\nВыбери тип напоминания:"),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔔 Одноразовое", callback_data=f"cal_remtype_none_{year}_{month}_{day}")],
            [InlineKeyboardButton("📅 Ежедневно", callback_data=f"cal_remtype_daily_{year}_{month}_{day}")],
            [InlineKeyboardButton("📆 По дням", callback_data=f"cal_remtype_weekly_{year}_{month}_{day}")],
            [InlineKeyboardButton("📅 Ежемесячное", callback_data=f"cal_remtype_monthly_{year}_{month}_{day}")],
            [InlineKeyboardButton("🎂 Ежегодное", callback_data=f"cal_remtype_yearly_{year}_{month}_{day}")],
            [btn_cancel()],
        ])
    )


@register_callback_handler("cal_set_bday_")
async def cb_calendar_set_bday(query, context, data, user, chat_id, bot):
    """Создать день рождения на выбранный день из календаря."""
    from datetime import date
    parts = data.split("_")
    year = int(parts[3])
    month = int(parts[4])
    day = int(parts[5])

    start_process(user.id, chat_id, "birthday_from_calendar", {
        "step": "waiting_name",
        "prefilled_date": date(year, month, day),
    }, query.message.message_id)

    await query.edit_message_text(
        _pad(f"🎂 *День рождения на {day}.{month:02d}*\n\nВведи имя именинника:"),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
    )
