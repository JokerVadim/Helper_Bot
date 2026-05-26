"""Reminders and timers domain processor."""
import asyncio
import logging
import calendar
import re
from datetime import datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from db import (
    db_save_reminder, db_has_duplicate_reminder, db_get_reminder, db_update_reminder,
)
from keyboards import btn_cancel, show_main_menu
from handlers.session import register_message, start_process, finish_process, processes, _store_memory_reminder
from handlers.reminders import (
    next_reminder_id, _schedule_reminder, _cancel_reminder_job,
    _find_memory_reminder, _row_to_reminder, _remove_memory_reminder,
    show_reminders_ui,
)
from handlers.processors import register_message_handler, register_callback_handler
from utils import md, _pad

# ─── Action Mode ──────────────────────────────────────────────────────────────
_reminder_action_modes: dict[int, str] = {}

def _get_reminder_action_mode(user_id: int) -> str:
    return _reminder_action_modes.get(user_id, "")

def _set_reminder_action_mode(user_id: int, mode: str):
    if mode:
        _reminder_action_modes[user_id] = mode
    else:
        _reminder_action_modes.pop(user_id, None)
from utils.time_utils import (
    parse_reminder_time_arg, parse_time_arg, parse_clock,
    next_daily_at, next_monthly_at, next_yearly_at, describe_when,
    _repeat_icon,
)

logger = logging.getLogger(__name__)


# ─── Reminder ─────────────────────────────────────────────────────────────────

async def _create_reminder_from_state(context, bot, user_id: int, chat_id: int, state: dict, text: str):
    fire_at = state["fire_at"]
    repeat_type = state.get("repeat_type", "none")
    minutes = state.get("minutes", 0)
    repeat_days = state.get("repeat_days", "")

    rid = next_reminder_id(chat_id)
    _schedule_reminder(context.job_queue, chat_id, rid, text, fire_at, False, repeat_type, minutes=minutes, repeat_days=repeat_days)
    await db_save_reminder(chat_id, rid, text, fire_at, False, repeat_type, minutes, repeat_days)

    from handlers.reminders import auto_assign_reminder_tags
    await asyncio.to_thread(auto_assign_reminder_tags, chat_id, rid, repeat_type)

    await finish_process(bot, user_id, show_menu=False)

    if repeat_type == "minutes":
        desc = f"каждые {minutes} минут"
    elif repeat_type == "interval_days":
        desc = f"каждые {minutes} дн. в {fire_at.strftime('%H:%M')}"
    elif repeat_type == "weekly" and repeat_days:
        from utils.time_utils import WEEKDAY_NAMES
        day_names = []
        try:
            days = [int(d.strip()) for d in repeat_days.split(",") if d.strip()]
            for d in days:
                if 0 <= d < 7:
                    day_names.append(WEEKDAY_NAMES[d])
        except (ValueError, TypeError):
            pass
        desc = f"по {'⋅'.join(day_names)}" if day_names else "по дням"
    else:
        desc = describe_when(fire_at)
    await show_main_menu(bot, user_id, f"✅ {_repeat_icon(repeat_type)} Напоминание ({desc}) создано!")

@register_message_handler("reminder")
async def handle_reminder_message(update, context, proc, state):
    from telegram import InlineKeyboardMarkup
    user = update.effective_user
    chat_id = update.effective_chat.id
    message = update.message or update.effective_message
    text = message.text.strip() if message.text else ""
    bot = context.bot
    register_message(user.id, chat_id, message.message_id)

    step = state.get("step")

    if step == "waiting_repeat":
        reply = await message.reply_text(
            "Выбери тип напоминания кнопкой ниже.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔔 Одноразовое", callback_data="remtype_none")],
                [InlineKeyboardButton("📅 Ежедневно", callback_data="remtype_daily")],
                [InlineKeyboardButton("📆 По дням", callback_data="remtype_weekly")],
                [InlineKeyboardButton("📅 Ежемесячное", callback_data="remtype_monthly")],
                [InlineKeyboardButton("🎂 Ежегодное", callback_data="remtype_yearly")],
                [btn_cancel()],
            ])
        )
        register_message(user.id, chat_id, reply.message_id)
        return

    if step == "waiting_week_days":
        # Пользователь ввёл текст вместо кнопок — парсим как дни недели
        from utils.time_utils import WEEKDAY_NAMES
        day_name_to_idx = {name.lower(): i for i, name in enumerate(WEEKDAY_NAMES)}
        day_name_to_idx_full = {
            "понедельник": 0, "вторник": 1, "среда": 2, "четверг": 3,
            "пятница": 4, "суббота": 5, "воскресенье": 6,
        }
        day_name_to_idx.update(day_name_to_idx_full)

        clean = text.strip().lower()
        parts = [p.strip() for p in clean.replace(",", " ").split() if p.strip()]

        selected = []
        for part in parts:
            if part.isdigit() and 0 <= int(part) <= 6:
                selected.append(int(part))
            elif part in day_name_to_idx:
                selected.append(day_name_to_idx[part])

        if not selected:
            reply = await message.reply_text(
                "❌ Не понял дни. Напиши через запятую, например:\n"
                "• `1,3,5` — Пн, Ср, Пт\n"
                "• `пн, ср, пт`\n"
                "• `понедельник среда пятница`",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
            )
            register_message(user.id, chat_id, reply.message_id)
            return

        state["repeat_days"] = ",".join(str(d) for d in sorted(selected))
        state["repeat_type"] = "weekly"
        state["step"] = "waiting_time"
        day_names = "⋅".join(WEEKDAY_NAMES[d] for d in sorted(selected))
        reply = await message.reply_text(
            f"📆 По {day_names}\n\nВведи время:\n\n• *14:30* — сегодня\n• *завтра 14:30*\n• *1h30m* — через промежуток",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        register_message(user.id, chat_id, reply.message_id)
        return

    if step == "waiting_month_day":
        clean = text.strip()
        if not clean.isdigit() or not (1 <= int(clean) <= 31):
            reply = await message.reply_text(
                "❌ Введи число месяца от 1 до 31:",
                reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
            )
            register_message(user.id, chat_id, reply.message_id)
            return
        state["month_day"] = int(clean)
        state["step"] = "waiting_repeat_clock"
        reply = await message.reply_text(
            f"📅 Каждый месяц {state['month_day']} числа.\n\nТеперь введи время:\n\n• *10:00*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        register_message(user.id, chat_id, reply.message_id)
        return

    if step == "waiting_year_date":
        m = re.fullmatch(r'\s*(\d{1,2})\.(\d{1,2})\s*', text)
        if not m:
            reply = await message.reply_text(
                "❌ Введи дату в формате *дд.мм*, например *12.08*:",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
            )
            register_message(user.id, chat_id, reply.message_id)
            return
        day, month_val = int(m.group(1)), int(m.group(2))
        if month_val < 1 or month_val > 12 or day < 1 or day > calendar.monthrange(datetime.now().year, month_val)[1]:
            reply = await message.reply_text(
                "❌ Такой даты нет. Введи дату в формате *дд.мм*:",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
            )
            register_message(user.id, chat_id, reply.message_id)
            return
        state["year_day"] = day
        state["year_month"] = month_val
        state["step"] = "waiting_repeat_clock"
        reply = await message.reply_text(
            f"🎂 Каждый год {day:02d}.{month_val:02d}.\n\nТеперь введи время:\n\n• *09:00*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        register_message(user.id, chat_id, reply.message_id)
        return

    if step == "waiting_repeat_clock":
        clock = parse_clock(text)
        if not clock:
            reply = await message.reply_text(
                "❌ Введи время в формате *чч:мм*, например *10:00*:",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
            )
            register_message(user.id, chat_id, reply.message_id)
            return
        hour, minute = clock
        repeat_type = state.get("repeat_type", "none")
        if repeat_type == "monthly":
            fire_at = next_monthly_at(state["month_day"], hour, minute)
        elif repeat_type == "yearly":
            fire_at = next_yearly_at(state["year_day"], state["year_month"], hour, minute)
        else:
            fire_at = next_daily_at(hour, minute)
        state["fire_at"] = fire_at
        state["step"] = "waiting_text"
        reply = await message.reply_text(
            f"⏰ Время: *{describe_when(fire_at)}*\n\nЧто напомнить?",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        register_message(user.id, chat_id, reply.message_id)
        return

    if step == "waiting_one_time_date":
        clean = text.strip().lower()
        if clean and clean != "-":
            now = datetime.now()
            date_part = None
            date_match = re.search(r'(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?', clean)
            if date_match:
                day = int(date_match.group(1))
                month = int(date_match.group(2))
                year = int(date_match.group(3)) if date_match.group(3) else now.year
                try:
                    date_part = now.replace(year=year, month=month, day=day)
                except ValueError:
                    pass
            elif "послезавтра" in clean:
                date_part = now + timedelta(days=2)
            elif "завтра" in clean:
                date_part = now + timedelta(days=1)
            elif "сегодня" in clean:
                date_part = now

            if date_part:
                state["one_time_date"] = date_part.strftime("%Y-%m-%d")
            else:
                reply = await message.reply_text(
                    "❌ Не понял дату. Попробуй:\n"
                    "• `25.05` — 25 мая\n"
                    "• `25.05.2026` — 25 мая 2026\n"
                    "• `завтра`\n"
                    "• `-` — без даты",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
                )
                register_message(user.id, chat_id, reply.message_id)
                return
        else:
            state.pop("one_time_date", None)

        state["step"] = "waiting_one_time_clock"
        reply = await message.reply_text(
            "Введи время:\n\n"
            "• *14:30*\n"
            "• *1h30m* — через промежуток",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        register_message(user.id, chat_id, reply.message_id)
        return

    if step == "waiting_one_time_clock":
        clock = parse_clock(text)
        if clock:
            h, mn = clock
            date_str = state.get("one_time_date")
            now = datetime.now()
            if date_str:
                base = datetime.strptime(date_str, "%Y-%m-%d")
                fire_at = base.replace(hour=h, minute=mn, second=0, microsecond=0)
                if fire_at <= now:
                    fire_at += timedelta(days=1)
            else:
                fire_at = now.replace(hour=h, minute=mn, second=0, microsecond=0)
                if fire_at <= now:
                    fire_at += timedelta(days=1)
        else:
            # пробуем относительный формат (1h30m)
            fire_at = parse_time_arg(text)
            if not fire_at or fire_at <= datetime.now() - timedelta(minutes=1):
                reply = await message.reply_text(
                    "❌ Не понял время. Введи *чч:мм*, например *14:30*:",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
                )
                register_message(user.id, chat_id, reply.message_id)
                return

        state["fire_at"] = fire_at
        state["step"] = "waiting_text"

        reply = await message.reply_text(
            f"⏰ Время: *{describe_when(fire_at)}*\n\nЧто напомнить?",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        register_message(user.id, chat_id, reply.message_id)
        return

    if step == "waiting_time":
        repeat_type = state.get("repeat_type", "none")
        fire_at = parse_reminder_time_arg(text, repeat_type)
        if not fire_at:
            reply = await message.reply_text(
                "❌ Не понял время. Попробуй:\n"
                "• *14:30* — сегодня в 14:30\n"
                "• *завтра 14:30*\n"
                "• *послезавтра 14:30*\n"
                "• *25.05 14:30* — конкретная дата\n"
                "• *07:30* — для ежедневного\n"
                "• *5 10:00* — для ежемесячного\n"
                "• *12.08 09:00* — для ежегодного\n"
                "• *1h30m* — через 1 час 30 минут",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
            )
            register_message(user.id, chat_id, reply.message_id)
            return

        state["fire_at"] = fire_at
        state["step"] = "waiting_text"

        reply = await message.reply_text(
            f"⏰ Время: *{describe_when(fire_at)}*\n\nЧто напомнить?",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        register_message(user.id, chat_id, reply.message_id)
        return

    if step == "waiting_interval_days":
        # Парсим: "3 08:00"
        parts = text.strip().split()
        if len(parts) < 2 or not parts[0].isdigit() or int(parts[0]) < 1:
            reply = await message.reply_text(
                "❌ Введи количество дней и время:\n\n• *3 08:00* — каждые 3 дня в 08:00",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
            )
            register_message(user.id, chat_id, reply.message_id)
            return

        days = int(parts[0])
        clock = parse_clock(parts[1])
        if not clock:
            reply = await message.reply_text(
                "❌ Неверный формат времени. Введи *чч:мм*, например *08:00*:",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
            )
            register_message(user.id, chat_id, reply.message_id)
            return

        hour, minute = clock
        now = datetime.now()
        fire_at = (now + timedelta(days=days)).replace(hour=hour, minute=minute, second=0, microsecond=0)

        state["fire_at"] = fire_at
        state["repeat_type"] = "interval_days"
        state["minutes"] = days  # хранит кол-во дней
        state["step"] = "waiting_text"
        reply = await message.reply_text(
            f"🔄 Каждые {days} дн. в {hour:02d}:{minute:02d}\n\nЧто напомнить?",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        register_message(user.id, chat_id, reply.message_id)
        return

    if step == "waiting_minutes":
        minutes_text = text.strip()
        if not minutes_text.isdigit() or int(minutes_text) < 1:
            reply = await message.reply_text(
                "❌ Введи число минут (от 1):",
                reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
            )
            register_message(user.id, chat_id, reply.message_id)
            return

        minutes = int(minutes_text)
        state["minutes"] = minutes
        state["step"] = "waiting_text"
        state["fire_at"] = datetime.now() + timedelta(minutes=minutes)

        reply = await message.reply_text(
            f"⏱ Каждые *{minutes} минут*\n\nЧто напомнить?",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        register_message(user.id, chat_id, reply.message_id)
        return

    elif step == "waiting_text":
        fire_at = state["fire_at"]
        repeat_type = state.get("repeat_type", "none")

        if await db_has_duplicate_reminder(chat_id, text, fire_at, repeat_type):
            reply = await message.reply_text(
                _pad("⚠️ Такое напоминание уже существует.\n\nСоздать ещё одно такое же?"),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Всё равно создать", callback_data="reminder_force_create")],
                    [btn_cancel()],
                ])
            )
            register_message(user.id, chat_id, reply.message_id)
            state["pending_duplicate_text"] = text
            return

        await _create_reminder_from_state(context, bot, user.id, chat_id, state, text)


# ─── Reminder from Calendar ───────────────────────────────────────────────────

@register_callback_handler("cal_remtype_")
async def cb_cal_remtype(query, context, data, user, chat_id, bot):
    """Выбор типа напоминания из календаря."""
    from telegram import InlineKeyboardMarkup
    parts = data.split("_")
    repeat_type = parts[2]
    year = int(parts[3])
    month = int(parts[4])
    day = int(parts[5])

    from datetime import date as dt_date
    prefilled_date = dt_date(year, month, day)

    if user.id not in processes or processes[user.id]["type"] != "reminder_from_calendar":
        await query.answer("Сессия не найдена", show_alert=True)
        return

    proc = processes[user.id]
    proc["state"]["repeat_type"] = repeat_type

    if repeat_type == "none":
        proc["state"]["step"] = "waiting_time"
        await query.edit_message_text(
            _pad("🔔 Одноразовое\n\nВведи время в формате *чч:мм*, например *14:30*:"),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
    elif repeat_type == "daily":
        proc["state"]["step"] = "waiting_time"
        await query.edit_message_text(
            _pad("📅 Ежедневно\n\nВведи время в формате *чч:мм*, например *08:00*:"),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
    elif repeat_type == "weekly":
        proc["state"]["step"] = "waiting_week_days"
        proc["state"]["repeat_days"] = ""
        days_keyboard = []
        row = []
        from utils.time_utils import WEEKDAY_NAMES
        for i in range(7):
            row.append(InlineKeyboardButton(f"☐ {WEEKDAY_NAMES[i]}", callback_data=f"cal_weekpick_toggle_{i}"))
            if (i + 1) % 4 == 0:
                days_keyboard.append(row)
                row = []
        if row:
            days_keyboard.append(row)
        days_keyboard.append([InlineKeyboardButton("✅ OK", callback_data="cal_weekpick_done")])
        days_keyboard.append([btn_cancel()])
        await query.edit_message_text(
            _pad("📆 *Выбери дни недели*\n\nНажимай на дни, чтобы выбрать/снять.\nЗатем нажми ✅ OK."),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(days_keyboard)
        )
    elif repeat_type == "monthly":
        proc["state"]["step"] = "waiting_time"
        proc["state"]["month_day"] = prefilled_date.day
        await query.edit_message_text(
            _pad(f"📅 Ежемесячно, *{prefilled_date.day}* числа\n\nВведи время в формате *чч:мм*, например *10:00*:"),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
    elif repeat_type == "yearly":
        proc["state"]["step"] = "waiting_time"
        proc["state"]["year_day"] = prefilled_date.day
        proc["state"]["year_month"] = prefilled_date.month
        await query.edit_message_text(
            _pad(f"🎂 Ежегодно, *{prefilled_date.day:02d}.{prefilled_date.month:02d}*\n\nВведи время в формате *чч:мм*, например *09:00*:"),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )


@register_callback_handler("cal_weekpick_toggle_")
async def cb_cal_weekpick_toggle(query, context, data, user, chat_id, bot):
    """Переключение дня недели в календарном напоминании."""
    from telegram import InlineKeyboardMarkup
    day_idx = int(data.split("_")[-1])
    proc = processes.get(user.id)
    if not proc or proc.get("type") != "reminder_from_calendar":
        await query.answer("Сессия не найдена", show_alert=True)
        return
    selected_str = proc["state"].get("repeat_days", "")
    selected = set(int(d) for d in selected_str.split(",") if d.strip().isdigit())
    if day_idx in selected:
        selected.remove(day_idx)
    else:
        selected.add(day_idx)
    proc["state"]["repeat_days"] = ",".join(str(d) for d in sorted(selected))
    from utils.time_utils import WEEKDAY_NAMES
    days_keyboard = []
    row = []
    for i in range(7):
        marker = "☑️" if i in selected else "☐"
        row.append(InlineKeyboardButton(f"{marker} {WEEKDAY_NAMES[i]}", callback_data=f"cal_weekpick_toggle_{i}"))
        if (i + 1) % 4 == 0:
            days_keyboard.append(row)
            row = []
    if row:
        days_keyboard.append(row)
    days_keyboard.append([
        InlineKeyboardButton("✅ OK", callback_data="cal_weekpick_done"),
        btn_cancel()
    ])
    await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(days_keyboard))
    await query.answer(f"✅ {', '.join(WEEKDAY_NAMES[d] for d in sorted(selected))}")


@register_callback_handler("cal_weekpick_done")
async def cb_cal_weekpick_done(query, context, data, user, chat_id, bot):
    """Подтверждение выбора дней недели."""
    from telegram import InlineKeyboardMarkup
    proc = processes.get(user.id)
    if not proc or proc.get("type") != "reminder_from_calendar":
        await query.answer("Сессия не найдена", show_alert=True)
        return
    selected_str = proc["state"].get("repeat_days", "")
    if not selected_str:
        await query.answer("❗️ Выбери хотя бы один день!", show_alert=True)
        return
    proc["state"]["step"] = "waiting_time"
    await query.edit_message_text(
        _pad("📆 Дни выбраны.\n\nТеперь введи время в формате *чч:мм*, например *10:00*:"),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
    )


@register_message_handler("reminder_from_calendar")
async def handle_reminder_from_calendar(update, context, proc, state):
    from telegram import InlineKeyboardMarkup
    user = update.effective_user
    chat_id = update.effective_chat.id
    message = update.message or update.effective_message
    text = message.text.strip() if message.text else ""
    bot = context.bot
    register_message(user.id, chat_id, message.message_id)

    step = state.get("step")
    prefilled_date = state.get("prefilled_date")
    repeat_type = state.get("repeat_type", "none")

    if step == "waiting_time":
        clock = parse_clock(text)
        if not clock:
            reply = await message.reply_text(
                _pad("❌ Не понял время. Введи в формате *чч:мм*, например *14:30*:"),
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
            )
            register_message(user.id, chat_id, reply.message_id)
            return

        hour, minute = clock

        if repeat_type == "monthly":
            month_day = state.get("month_day", prefilled_date.day)
            fire_at = next_monthly_at(month_day, hour, minute)
        elif repeat_type == "yearly":
            yday = state.get("year_day", prefilled_date.day)
            ymonth = state.get("year_month", prefilled_date.month)
            fire_at = next_yearly_at(yday, ymonth, hour, minute)
        elif repeat_type == "daily":
            fire_at = next_daily_at(hour, minute)
        elif repeat_type == "weekly":
            fire_at = next_daily_at(hour, minute)
        else:
            # none — одноразовое на выбранную дату
            fire_at = datetime.combine(prefilled_date, datetime.min.time()).replace(hour=hour, minute=minute, second=0, microsecond=0)
            now = datetime.now()
            if fire_at <= now:
                fire_at += timedelta(days=1)

        state["fire_at"] = fire_at
        state["step"] = "waiting_text"

        reply = await message.reply_text(
            f"⏰ Время: *{describe_when(fire_at)}*\n\nЧто напомнить?",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        register_message(user.id, chat_id, reply.message_id)
        return

    if step == "waiting_week_days":
        # Пользователь ввёл текст вместо кнопок
        from utils.time_utils import WEEKDAY_NAMES
        day_name_to_idx = {name.lower(): i for i, name in enumerate(WEEKDAY_NAMES)}
        day_name_to_idx.update({
            "понедельник": 0, "вторник": 1, "среда": 2, "четверг": 3,
            "пятница": 4, "суббота": 5, "воскресенье": 6,
        })
        clean = text.strip().lower()
        parts = [p.strip() for p in clean.replace(",", " ").split() if p.strip()]
        selected = []
        for part in parts:
            if part.isdigit() and 0 <= int(part) <= 6:
                selected.append(int(part))
            elif part in day_name_to_idx:
                selected.append(day_name_to_idx[part])
        if not selected:
            reply = await message.reply_text(
                "❌ Не понял дни. Напиши через запятую, например:\n"
                "• `1,3,5` — Пн, Ср, Пт\n"
                "• `пн, ср, пт`",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
            )
            register_message(user.id, chat_id, reply.message_id)
            return
        state["repeat_days"] = ",".join(str(d) for d in sorted(selected))
        state["repeat_type"] = "weekly"
        state["step"] = "waiting_time"
        day_names = "⋅".join(WEEKDAY_NAMES[d] for d in sorted(selected))
        reply = await message.reply_text(
            f"📆 По {day_names}\n\nВведи время в формате *чч:мм*, например *10:00*:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        register_message(user.id, chat_id, reply.message_id)
        return

    if step == "waiting_text":
        fire_at = state["fire_at"]
        repeat_type = state.get("repeat_type", "none")

        if await db_has_duplicate_reminder(chat_id, text, fire_at, repeat_type):
            reply = await message.reply_text(
                _pad("⚠️ Такое напоминание уже существует.\n\nСоздать ещё одно такое же?"),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Всё равно создать", callback_data="reminder_force_create")],
                    [btn_cancel()],
                ])
            )
            register_message(user.id, chat_id, reply.message_id)
            state["pending_duplicate_text"] = text
            return

        await _create_reminder_from_state(context, bot, user.id, chat_id, state, text)


@register_callback_handler("reminder_force_create")
async def cb_reminder_force_create(query, context, data, user, chat_id, bot):
    proc = processes.get(user.id)
    if not proc or proc.get("type") not in {"reminder", "reminder_from_calendar"}:
        await query.answer("Сессия не найдена", show_alert=True)
        return
    state = proc["state"]
    text = state.get("pending_duplicate_text")
    if not text:
        await query.answer("Текст не найден", show_alert=True)
        return
    state.pop("pending_duplicate_text", None)
    await query.answer("Создаю")
    await _create_reminder_from_state(context, bot, user.id, chat_id, state, text)


# ─── Timer ────────────────────────────────────────────────────────────────────

@register_message_handler("timer")
async def handle_timer_message(update, context, proc, state):
    from telegram import InlineKeyboardMarkup
    user = update.effective_user
    chat_id = update.effective_chat.id
    message = update.message or update.effective_message
    text = message.text.strip() if message.text else ""
    bot = context.bot
    register_message(user.id, chat_id, message.message_id)

    step = state.get("step")

    if step == "waiting_time":
        fire_at = parse_time_arg(text)
        if not fire_at:
            reply = await message.reply_text(
                "❌ Неверный формат. Введи число минут:\n• *10* — 10 минут\n• *60* — 1 час",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
            )
            register_message(user.id, chat_id, reply.message_id)
            return

        seconds = int((fire_at - datetime.now()).total_seconds())
        state["seconds"] = seconds
        state["step"] = "waiting_text"

        reply = await message.reply_text(
            "📝 Подпись таймера (или `-` чтобы пропустить):",
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        register_message(user.id, chat_id, reply.message_id)

    elif step == "waiting_text":
        seconds = state["seconds"]
        timer_text = text if text not in ("", "-") else "⏱"
        fire_at = datetime.now() + timedelta(seconds=seconds)
        rid = next_reminder_id(chat_id)
        _schedule_reminder(context.job_queue, chat_id, rid, timer_text, fire_at, True, "none")
        await db_save_reminder( chat_id, rid, timer_text, fire_at, True)

        mins, secs = divmod(seconds, 60)
        duration = f"{mins}м {secs}с" if mins else f"{secs}с"
        await finish_process(bot, user.id, show_menu=False)
        await show_main_menu(bot, user.id, f"✅ Таймер на *{duration}* запущен!")


# ─── Edit Reminder ────────────────────────────────────────────────────────────

@register_message_handler("edit_reminder")
async def handle_edit_reminder(update, context, proc, state):
    from telegram import InlineKeyboardMarkup
    user = update.effective_user
    chat_id = update.effective_chat.id
    message = update.message or update.effective_message
    text = message.text.strip() if message.text else ""
    bot = context.bot
    register_message(user.id, chat_id, message.message_id)

    rid = state.get("rid")
    item = _find_memory_reminder(chat_id, rid)
    if not item:
        row = await db_get_reminder( chat_id, rid)
        item = _row_to_reminder(row) if row else None
    if not item:
        await finish_process(bot, user.id, show_menu=True, menu_text="❌ Напоминание не найдено.")
        return

    step = state.get("step")

    if step == "waiting_text":
        item["text"] = text
        await db_update_reminder( chat_id, rid, text=text)
        if item.get("job"):
            _cancel_reminder_job(chat_id, rid)
            _schedule_reminder(
                context.job_queue, chat_id, rid, text, item["time"],
                item.get("is_timer", False), item.get("repeat_type", "none"),
                minutes=item.get("minutes", 0)
            )
        await finish_process(bot, user.id, show_menu=True, menu_text="✅ Текст напоминания обновлён.")
        return

    if step == "waiting_week_days":
        from utils.time_utils import WEEKDAY_NAMES
        day_name_to_idx = {name.lower(): i for i, name in enumerate(WEEKDAY_NAMES)}
        day_name_to_idx.update({
            "понедельник": 0, "вторник": 1, "среда": 2, "четверг": 3,
            "пятница": 4, "суббота": 5, "воскресенье": 6,
        })
        clean = text.strip().lower()
        parts = [p.strip() for p in clean.replace(",", " ").split() if p.strip()]
        selected = []
        for part in parts:
            if part.isdigit() and 0 <= int(part) <= 6:
                selected.append(int(part))
            elif part in day_name_to_idx:
                selected.append(day_name_to_idx[part])
        if not selected:
            reply = await message.reply_text("❌ Не понял дни. Напиши через запятую, например `1,3,5` или `пн,ср,пт`:", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[btn_cancel()]]))
            register_message(user.id, chat_id, reply.message_id)
            return
        state["repeat_days"] = ",".join(str(d) for d in sorted(selected))
        state["repeat_type"] = "weekly"
        state["step"] = "waiting_repeat_clock"
        day_names = "⋅".join(WEEKDAY_NAMES[d] for d in sorted(selected))
        reply = await message.reply_text(_pad(f"📆 По {day_names}\n\nТеперь введи время в формате *чч:мм*:"), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[btn_cancel()]]))
        register_message(user.id, chat_id, reply.message_id)
        return

    if step == "waiting_month_day":
        clean = text.strip()
        if not clean.isdigit() or not (1 <= int(clean) <= 31):
            reply = await message.reply_text(_pad("❌ Введи число месяца от 1 до 31:"), reply_markup=InlineKeyboardMarkup([[btn_cancel()]]))
            register_message(user.id, chat_id, reply.message_id)
            return
        state["month_day"] = int(clean)
        state["step"] = "waiting_repeat_clock"
        reply = await message.reply_text(_pad("Теперь введи время в формате *чч:мм*:"), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[btn_cancel()]]))
        register_message(user.id, chat_id, reply.message_id)
        return

    if step == "waiting_year_date":
        m = re.fullmatch(r'\s*(\d{1,2})\.(\d{1,2})\s*', text)
        if not m:
            reply = await message.reply_text(_pad("❌ Введи дату в формате *дд.мм*:"), reply_markup=InlineKeyboardMarkup([[btn_cancel()]]))
            register_message(user.id, chat_id, reply.message_id)
            return
        day, month_val = int(m.group(1)), int(m.group(2))
        if month_val < 1 or month_val > 12 or day < 1 or day > calendar.monthrange(datetime.now().year, month_val)[1]:
            reply = await message.reply_text(_pad("❌ Такой даты нет. Введи дату в формате *дд.мм*:"), reply_markup=InlineKeyboardMarkup([[btn_cancel()]]))
            register_message(user.id, chat_id, reply.message_id)
            return
        state["year_day"] = day
        state["year_month"] = month_val
        state["step"] = "waiting_repeat_clock"
        reply = await message.reply_text(_pad("Теперь введи время в формате *чч:мм*:"), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[btn_cancel()]]))
        register_message(user.id, chat_id, reply.message_id)
        return

    if step == "waiting_repeat_clock":
        clock = parse_clock(text)
        if not clock:
            reply = await message.reply_text(_pad("❌ Введи время в формате *чч:мм*:"), reply_markup=InlineKeyboardMarkup([[btn_cancel()]]))
            register_message(user.id, chat_id, reply.message_id)
            return
        hour, minute = clock
        repeat_type = state.get("repeat_type", item.get("repeat_type", "none"))
        if repeat_type == "monthly":
            fire_at = next_monthly_at(state["month_day"], hour, minute)
        elif repeat_type == "yearly":
            fire_at = next_yearly_at(state["year_day"], state["year_month"], hour, minute)
        else:
            fire_at = next_daily_at(hour, minute)
        _cancel_reminder_job(chat_id, rid)
        item["time"] = fire_at
        item["delivered"] = False
        _schedule_reminder(context.job_queue, chat_id, rid, item["text"], fire_at, item.get("is_timer", False), repeat_type, minutes=item.get("minutes", 0))
        await db_update_reminder( chat_id, rid, fire_at=fire_at, delivered=False, minutes=item.get("minutes", 0))
        await finish_process(bot, user.id, show_menu=True, menu_text="✅ Время напоминания обновлено.")
        return

    if step == "waiting_time":
        repeat_type = state.get("repeat_type", item.get("repeat_type", "none"))
        fire_at = parse_reminder_time_arg(text, repeat_type)
        if not fire_at:
            reply = await message.reply_text(_pad("❌ Не понял время. Попробуй ещё раз:"), reply_markup=InlineKeyboardMarkup([[btn_cancel()]]))
            register_message(user.id, chat_id, reply.message_id)
            return
        _cancel_reminder_job(chat_id, rid)
        item["time"] = fire_at
        item["delivered"] = False
        _schedule_reminder(context.job_queue, chat_id, rid, item["text"], fire_at, item.get("is_timer", False), repeat_type, minutes=item.get("minutes", 0))
        await db_update_reminder( chat_id, rid, fire_at=fire_at, delivered=False, minutes=item.get("minutes", 0))
        await finish_process(bot, user.id, show_menu=True, menu_text="✅ Время напоминания обновлено.")


# ─── Edit Timer Name ──────────────────────────────────────────────────────────

@register_message_handler("edit_timer_name")
async def handle_edit_timer_name(update, context, proc, state):
    user = update.effective_user
    chat_id = update.effective_chat.id
    message = update.message or update.effective_message
    text = message.text.strip() if message.text else ""
    bot = context.bot
    register_message(user.id, chat_id, message.message_id)

    rid = state.get("rid")
    item = _find_memory_reminder(chat_id, rid)
    if not item:
        await finish_process(bot, user.id, show_menu=True, menu_text="❌ Таймер не найден.")
        return

    item["text"] = text
    await db_update_reminder( chat_id, rid, text=text)
    await finish_process(bot, user.id, show_menu=True, menu_text="✅ Название таймера обновлено.")


# ─── Edit Timer Time ─────────────────────────────────────────────────────────

@register_message_handler("edit_timer_time")
async def handle_edit_timer_time(update, context, proc, state):
    from telegram import InlineKeyboardMarkup
    user = update.effective_user
    chat_id = update.effective_chat.id
    message = update.message or update.effective_message
    text = message.text.strip() if message.text else ""
    bot = context.bot
    register_message(user.id, chat_id, message.message_id)

    rid = state.get("rid")
    item = _find_memory_reminder(chat_id, rid)
    if not item:
        await finish_process(bot, user.id, show_menu=True, menu_text="❌ Таймер не найден.")
        return

    fire_at = parse_reminder_time_arg(text, "none")
    if not fire_at:
        reply = await message.reply_text(_pad("❌ Не понял время. Попробуй ещё раз:"), reply_markup=InlineKeyboardMarkup([[btn_cancel()]]))
        register_message(user.id, chat_id, reply.message_id)
        return

    _cancel_reminder_job(chat_id, rid)
    item["time"] = fire_at
    item["delivered"] = False
    _schedule_reminder(context.job_queue, chat_id, rid, item["text"], fire_at, True, "none", minutes=0)
    await db_update_reminder( chat_id, rid, fire_at=fire_at, delivered=False, minutes=0)
    await finish_process(bot, user.id, show_menu=True, menu_text="✅ Время таймера обновлено.")


# ─── Reminder Tags ────────────────────────────────────────────────────────────

@register_callback_handler("remindertags_")
async def cb_remindertags(query, context, data, user, chat_id, bot):
    rid = int(data.split("_")[1])
    from db import db
    from handlers.processors.tag_ui import show_tag_picker
    # Конвертируем rid → PK для работы с тегами
    row = await asyncio.to_thread(db.get_reminder, chat_id, rid)
    if not row:
        await query.answer("Напоминание не найдено.", show_alert=True)
        return
    reminder_pk = row["id"]
    await show_tag_picker(query, user.id, chat_id, "reminder", reminder_pk)


@register_callback_handler("remindertagedit_")
async def cb_remindertagedit(query, context, data, user, chat_id, bot):
    parts = data.split("_")
    rid = int(parts[1])
    tag_id = int(parts[2])
    from db import db
    from handlers.processors.tag_ui import show_tag_picker
    # Конвертируем rid → PK для работы с тегами
    row = await asyncio.to_thread(db.get_reminder, chat_id, rid)
    if not row:
        await query.answer("Напоминание не найдено.", show_alert=True)
        return
    reminder_pk = row["id"]
    tags = await asyncio.to_thread(db.get_reminder_tags, user.id, reminder_pk)
    existing = {t["id"] for t in tags}
    if tag_id in existing:
        await asyncio.to_thread(db.remove_reminder_tag, user.id, reminder_pk, tag_id)
    else:
        tag = await asyncio.to_thread(db.get_reminder_tag, user.id, tag_id)
        if tag:
            await asyncio.to_thread(db.add_reminder_tag, user.id, reminder_pk, tag["name"])
    await show_tag_picker(query, user.id, chat_id, "reminder", reminder_pk)


@register_callback_handler("remindertagnew_")
async def cb_remindertagnew(query, context, data, user, chat_id, bot):
    rid = int(data.split("_")[1])
    start_process(user.id, chat_id, "reminder_new_tag", {"step": "waiting_tag_name", "rid": rid}, query.message.message_id)
    await query.edit_message_text(
        _pad("🏷 *Новый тег*\n\nВведи название тега:"),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
    )


@register_message_handler("reminder_new_tag")
async def handle_reminder_new_tag(update, context, proc, state):
    from handlers.processors.tag_ui import show_tag_picker
    from telegram import InlineKeyboardMarkup
    user = update.effective_user
    chat_id = update.effective_chat.id
    message = update.message or update.effective_message
    text = message.text.strip() if message.text else ""
    bot = context.bot
    register_message(user.id, chat_id, message.message_id)

    if state.get("step") != "waiting_tag_name":
        return

    tag_name = text.strip()
    if not tag_name:
        reply = await message.reply_text(_pad("❌ Название тега не может быть пустым."), reply_markup=InlineKeyboardMarkup([[btn_cancel()]]))
        register_message(user.id, chat_id, reply.message_id)
        return

    from db import db
    rid = state["rid"]
    # Конвертируем rid → PK для работы с тегами
    row = await asyncio.to_thread(db.get_reminder, chat_id, rid)
    if not row:
        await finish_process(bot, user.id, show_menu=True, menu_text="❌ Напоминание не найдено.")
        return
    reminder_pk = row["id"]
    await asyncio.to_thread(db.get_or_create_reminder_tag, user.id, tag_name)
    await asyncio.to_thread(db.add_reminder_tag, user.id, reminder_pk, tag_name)
    await finish_process(bot, user.id, show_menu=False)
    await show_tag_picker(bot, user.id, chat_id, "reminder", reminder_pk,
                          message=f"✅ Тег *{md(tag_name)}* добавлен.",
                          is_new_message=True)


# ─── Snooze ──────────────────────────────────────────────────────────

@register_callback_handler("snooze_")
async def cb_snooze_reminder(query, context, data, user, chat_id, bot):
    _, rid_str, amount = data.split("_")
    rid = int(rid_str)
    delta = {"10m": timedelta(minutes=10), "1h": timedelta(hours=1), "1d": timedelta(days=1)}.get(amount)
    if not delta:
        await query.answer("❌ Неизвестный интервал", show_alert=True)
        return

    item = _find_memory_reminder(chat_id, rid)
    if not item:
        row = await db_get_reminder(chat_id, rid)
        item = _row_to_reminder(row) if row else None
    if not item:
        await query.answer("❌ Напоминание не найдено", show_alert=True)
        return

    new_time = datetime.now() + delta
    repeat_type = item.get("repeat_type", "none")
    text = str(item.get("text", ""))

    is_dup = await db_has_duplicate_reminder(chat_id, text, new_time, repeat_type)
    if is_dup:
        await query.answer("Такое напоминание уже есть!", show_alert=True)
        return

    _remove_memory_reminder(chat_id, rid)
    _cancel_reminder_job(chat_id, rid)

    minutes = item.get("minutes", 0)
    is_timer = bool(item.get("is_timer", False))
    new_item = {
        "id": rid,
        "text": text,
        "time": new_time,
        "job": None,
        "is_timer": is_timer,
        "repeat_type": repeat_type,
        "minutes": minutes,
        "delivered": False,
    }
    _store_memory_reminder(chat_id, new_item)
    _schedule_reminder(context.job_queue, chat_id, rid, text, new_time, is_timer, repeat_type, minutes=minutes)
    await db_update_reminder(chat_id, rid, fire_at=new_time, delivered=False, minutes=minutes)

    amount_label = {"10m": "10 минут", "1h": "1 час", "1d": "завтра"}.get(amount, amount)
    await show_main_menu(bot, user.id, f"⏰ Напоминание отложено на *{amount_label}*")


# ─── Tag filter (open_remindertag_) ──────────────────────────────────

@register_callback_handler("open_remindertag_")
async def cb_open_remindertag(query, context, data, user, chat_id, bot):
    tag_id = int(data.split("_")[2])
    await show_reminders_ui(query, chat_id, tag_id=tag_id)
