"""Reminder and timer callback handlers."""
import asyncio
import logging
from datetime import datetime, timedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from db import (
    db_get_reminder, db_delete_reminder, db_update_reminder,
    db_has_duplicate_reminder,
)

from utils import md, _pad
from keyboards import btn_menu, btn_cancel, show_main_menu
from handlers.session import (
    start_process, processes, reminders, _store_memory_reminder,
)
from handlers.reminders import (
    _cancel_reminder_job, _find_memory_reminder, _remove_memory_reminder,
    _schedule_reminder, _row_to_reminder, show_reminders_ui,
    show_reminder_detail, show_timers_ui, auto_assign_reminder_tags,
)
from utils.time_utils import (
    _repeat_icon, _repeat_label, next_repeat_time, WEEKDAY_NAMES,
)

from handlers.callbacks.base import domain_handler

logger = logging.getLogger(__name__)


@domain_handler
async def handle_reminder_callbacks(query, context, data, user, chat_id, bot):
    # Reminders
    if data == "open_reminders":
        await show_reminders_ui(query, chat_id)
        return True

    if data.startswith("open_remindertag_"):
        tag_id = int(data.split("_")[2])
        await show_reminders_ui(query, chat_id, tag_id=tag_id)
        return True


    if data == "add_reminder":
        start_process(user.id, chat_id, "reminder", {"step": "waiting_repeat"}, query.message.message_id)
        await query.edit_message_text(
            _pad("⏰ Выбери тип напоминания:"),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔔 Одноразовое", callback_data="remtype_none")],
                [InlineKeyboardButton("🔄 Каждые N дней", callback_data="remtype_interval_days")],
                [InlineKeyboardButton("⏱ Каждые N минут", callback_data="remtype_minutes")],
                [InlineKeyboardButton("📅 Ежедневно", callback_data="remtype_daily")],
                [InlineKeyboardButton("📆 По дням", callback_data="remtype_weekly")],
                [InlineKeyboardButton("📅 Ежемесячное", callback_data="remtype_monthly")],
                [InlineKeyboardButton("🎂 Ежегодное", callback_data="remtype_yearly")],
                [btn_cancel()],
            ])
        )
        return True

    if data.startswith("remtype_"):
        repeat_type = data.split("_", 1)[1]
        if user.id not in processes or processes[user.id]["type"] != "reminder":
            start_process(user.id, chat_id, "reminder", {"step": "waiting_time"}, query.message.message_id)
        first_steps = {"none": "waiting_one_time_date", "daily": "waiting_time", "weekly": "waiting_week_days", "monthly": "waiting_month_day", "yearly": "waiting_year_date", "minutes": "waiting_minutes", "interval_days": "waiting_interval_days"}
        if repeat_type == "weekly":
            processes[user.id]["state"] = {"step": "waiting_week_days", "repeat_type": "weekly", "repeat_days": ""}
            days_keyboard = []
            row = []
            for i in range(7):
                row.append(InlineKeyboardButton(WEEKDAY_NAMES[i], callback_data=f"weekpick_toggle_{i}"))
                if (i + 1) % 4 == 0:
                    days_keyboard.append(row)
                    row = []
            if row:
                days_keyboard.append(row)
            days_keyboard.append([InlineKeyboardButton("✅ OK", callback_data="weekpick_done")])
            days_keyboard.append([btn_cancel()])
            await query.edit_message_text(
                _pad("📆 *Выбери дни недели*\n\nНажимай на дни, чтобы выбрать/снять.\nЗатем нажми ✅ OK."),
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(days_keyboard)
            )
            return True
        else:
            processes[user.id]["state"] = {"step": first_steps.get(repeat_type, "waiting_time"), "repeat_type": repeat_type}
        prompts = {
            "none": "Введи дату (или `-` чтобы пропустить):\n\n"
                    "• `25.05` — 25 мая\n"
                    "• `25.05.2026` — 25 мая 2026\n"
                    "• `завтра`\n"
                    "• `-` — сегодня (сработает в ближайшее время)",
            "interval_days": "Введи количество дней и время:\n\n• *3 08:00* — каждые 3 дня в 08:00\n• *7 09:00* — каждую неделю в 09:00",
            "minutes": "Введи интервал в минутах:\n\n• *15* — каждые 15 минут\n• *30* — каждые 30 минут\n• *60* — каждый час",
            "daily": "Введи время ежедневного напоминания:\n\n• *07:30*",
            "monthly": "Введи число месяца:\n\n• *5* — каждый месяц 5 числа\n• *31* — в коротких месяцах последний день",
            "yearly": "Введи дату:\n\n• *12.08* — каждый год 12 августа",
        }
        if repeat_type == "none":
            date_keyboard = [
                [
                    InlineKeyboardButton("📅 Сегодня", callback_data="onetime_date_today"),
                    InlineKeyboardButton("📅 Завтра", callback_data="onetime_date_tomorrow"),
                ],
                [btn_cancel()],
            ]
        else:
            date_keyboard = [[btn_cancel()]]
        await query.edit_message_text(
            f"{_repeat_icon(repeat_type)} Тип: *{md(_repeat_label(repeat_type))}*\n\n{prompts[repeat_type]}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(date_keyboard)
        )
        return True
    if data.startswith("viewrem_"):
        await show_reminder_detail(query, chat_id, int(data.split("_")[1]))
        return True

    # ── One-time date quick buttons ──
    if data == "onetime_date_today":
        proc = processes.get(user.id)
        if proc and proc.get("type") == "reminder":
            proc["state"]["one_time_date"] = datetime.now().strftime("%Y-%m-%d")
            proc["state"]["step"] = "waiting_one_time_clock"
            await query.edit_message_text(
                "📅 *Сегодня*\n\nВведи время:\n\n• *14:30*\n• *1h30m* — через промежуток",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
            )
        return True
    if data == "onetime_date_tomorrow":
        proc = processes.get(user.id)
        if proc and proc.get("type") == "reminder":
            proc["state"]["one_time_date"] = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
            proc["state"]["step"] = "waiting_one_time_clock"
            await query.edit_message_text(
                "📅 *Завтра*\n\nВведи время:\n\n• *14:30*\n• *1h30m* — через промежуток",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
            )
        return True

    # ── Week picker: toggle days ──
    if data.startswith("weekpick_toggle_"):
        day_idx = int(data.split("_")[-1])
        proc = processes.get(user.id)
        if not proc or proc.get("type") != "reminder":
            await query.answer("Сессия не найдена", show_alert=True)
            return True
        selected_str = proc["state"].get("repeat_days", "")
        selected = set(int(d) for d in selected_str.split(",") if d.strip().isdigit())
        if day_idx in selected:
            selected.remove(day_idx)
        else:
            selected.add(day_idx)
        proc["state"]["repeat_days"] = ",".join(str(d) for d in sorted(selected))
        # Обновляем клавиатуру
        days_keyboard = []
        row = []
        for i in range(7):
            marker = "☑️" if i in selected else "☐"
            row.append(InlineKeyboardButton(f"{marker} {WEEKDAY_NAMES[i]}", callback_data=f"weekpick_toggle_{i}"))
            if (i + 1) % 4 == 0:
                days_keyboard.append(row)
                row = []
        if row:
            days_keyboard.append(row)
        days_keyboard.append([
            InlineKeyboardButton("✅ OK", callback_data="weekpick_done"),
            btn_cancel()
        ])
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(days_keyboard))
        await query.answer(f"✅ {', '.join(WEEKDAY_NAMES[d] for d in sorted(selected))}")
        return True

    # ── Week picker: done ──
    if data == "weekpick_done":
        proc = processes.get(user.id)
        if not proc or proc.get("type") != "reminder":
            await query.answer("Сессия не найдена", show_alert=True)
            return True
        selected_str = proc["state"].get("repeat_days", "")
        if not selected_str:
            await query.answer("❗️ Выбери хотя бы один день!", show_alert=True)
            return True
        proc["state"]["step"] = "waiting_time"
        await query.edit_message_text(
            _pad("🕒 Отлично! Дни выбраны.\n\nТеперь введи время напоминания:\n\n• *14:30* — сегодня\n• *завтра 14:30*\n• *25.05 14:30*\n• *1h30m* — через промежуток"),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        return True

    # OK на сработавшем напоминании/таймере — удаляет сообщение
    # Для одноразовых напоминаний — также удаляет из БД
    if data.startswith("reminder_ok_"):
        rid = int(data.split("_")[-1])
        # Удаляем из памяти (на всякий случай)
        _remove_memory_reminder(chat_id, rid)
        # Проверяем по БД, одноразовое ли напоминание
        row = await db_get_reminder(chat_id, rid)
        if row:
            repeat_type = row.get("repeat_type") or "none"
            delivered = bool(row.get("delivered", 0))
            # Удаляем только если напоминание действительно доставлено (не отложено)
            if repeat_type == "none" and delivered:
                await db_delete_reminder(chat_id, rid)
        # Удаляем сообщение
        try:
            await bot.delete_message(chat_id=chat_id, message_id=query.message.message_id)
        except Exception:
            pass
        return True

    # X на напоминании "каждые N минут" - удаляет напоминание без подтверждения
    if data.startswith("reminder_del_"):
        rid = int(data.split("_")[-1])
        target = _find_memory_reminder(chat_id, rid)
        if target:
            _remove_memory_reminder(chat_id, rid)
        await db_delete_reminder(chat_id, rid)
        try:
            await bot.delete_message(chat_id=chat_id, message_id=query.message.message_id)
        except Exception:
            pass
        return True

    if data.startswith("delrem_"):
        rid = int(data.split("_")[1])
        target = _find_memory_reminder(chat_id, rid)
        if not target:
            row = await db_get_reminder(chat_id, rid)
            target = _row_to_reminder(row) if row else None
        if not target:
            await query.answer("❌ Напоминание не найдено", show_alert=True)
            return True

        # Показываем подтверждение удаления
        await query.edit_message_text(
            f"🗑 Удалить напоминание?\n\n{target['text']}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Да, удалить", callback_data=f"confirmdelrem_{rid}")],
                [InlineKeyboardButton("◀️ Назад", callback_data="open_reminders"), btn_menu()],
            ])
        )
        return True

    if data.startswith("confirmdelrem_"):
        rid = int(data.split("_")[1])
        _cancel_reminder_job(chat_id, rid)
        _remove_memory_reminder(chat_id, rid)
        await db_delete_reminder(chat_id, rid)
        try:
            await bot.delete_message(chat_id=chat_id, message_id=query.message.message_id)
        except Exception:
            pass
        await show_reminders_ui(query, chat_id, bot=bot, user_id=user.id)
        return True

    # TOGGLE режимов напоминаний
    if data.startswith("remindertogglemode_"):
        mode = data[19:]  # remindertogglemode_{mode}
        from handlers.processors.reminders import _get_reminder_action_mode, _set_reminder_action_mode
        current = _get_reminder_action_mode(user.id)
        if current == mode:
            _set_reminder_action_mode(user.id, "")
        else:
            _set_reminder_action_mode(user.id, mode)
        await show_reminders_ui(query, chat_id)
        return True

    if data.startswith("snooze_"):
        _, rid_str, amount = data.split("_")
        rid = int(rid_str)
        delta = {"10m": timedelta(minutes=10), "1h": timedelta(hours=1), "1d": timedelta(days=1)}.get(amount)
        if not delta:
            await query.answer("❌ Неизвестный интервал", show_alert=True)
            return True
        item = _find_memory_reminder(chat_id, rid)
        if not item:
            row = await db_get_reminder(chat_id, rid)
            item = _row_to_reminder(row) if row else None
        if not item:
            await query.answer("❌ Напоминание не найдено", show_alert=True)
            return True

        new_time = datetime.now() + delta
        is_timer = bool(item.get("is_timer", False))
        repeat_type = item.get("repeat_type", "none")
        text = str(item.get("text", ""))

        is_dup = await db_has_duplicate_reminder(chat_id, text, new_time, repeat_type)
        if is_dup:
            await query.answer("Такое напоминание уже есть!", show_alert=True)
            return True

        _remove_memory_reminder(chat_id, rid)
        _cancel_reminder_job(chat_id, rid)

        minutes = item.get("minutes", 0)
        new_item = {
            "id": rid,
            "text": text,
            "time": new_time,
            "is_timer": is_timer,
            "repeat_type": repeat_type,
            "minutes": minutes,
            "delivered": False,
        }

        _store_memory_reminder(chat_id, new_item)
        _schedule_reminder(context.job_queue, chat_id, rid, text, new_time, is_timer, repeat_type, minutes=minutes)

        await db_update_reminder(chat_id, rid, fire_at=new_time, delivered=False, minutes=minutes)

        amount_label = {"10m": "10 минут", "1h": "1 час", "1d": "завтра"}.get(amount, amount)
        await show_main_menu(context.bot, user.id, f"⏰ Напоминание отложено на *{amount_label}*")
        return True

    if data.startswith("editremtext_"):
        rid = int(data.split("_")[1])
        item = _find_memory_reminder(chat_id, rid)
        if not item:
            row = await db_get_reminder(chat_id, rid)
            item = _row_to_reminder(row) if row else None
        old_text = md(item["text"]) if item else ""
        start_process(user.id, chat_id, "edit_reminder", {"step": "waiting_text", "rid": rid}, query.message.message_id)
        await query.edit_message_text(_pad(f"✏️ *Редактировать текст*\n\nТекущий: `{old_text}`\n\nВведи новый текст:"), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[btn_cancel()]]))
        return True

    if data.startswith("editremtime_"):
        rid = int(data.split("_")[1])
        item = _find_memory_reminder(chat_id, rid)
        repeat_type = (item or {}).get("repeat_type", "none")
        first_steps = {"monthly": "waiting_month_day", "yearly": "waiting_year_date", "weekly": "waiting_week_days"}
        step = first_steps.get(repeat_type, "waiting_time")
        start_process(user.id, chat_id, "edit_reminder", {"step": step, "rid": rid, "repeat_type": repeat_type}, query.message.message_id)
        prompts = {"monthly": _pad("🕒 Введи новое число месяца:"), "yearly": _pad("🕒 Введи новую дату в формате *дд.мм*:")}
        await query.edit_message_text(prompts.get(repeat_type, _pad(f"🕒 Введи новое время для типа *{md(_repeat_label(repeat_type))}*:")), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[btn_cancel()]]))
        return True

    if data.startswith("editremrepeat_"):
        rid = int(data.split("_")[1])
        await query.edit_message_text(_pad("🔁 Выбери новый тип повтора:"), reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔔 Одноразовое", callback_data=f"setremrepeat_{rid}_none")],
            [InlineKeyboardButton("📅 Ежедневно", callback_data=f"setremrepeat_{rid}_daily")],
            [InlineKeyboardButton("📆 По дням", callback_data=f"setremrepeat_{rid}_weekly")],
            [InlineKeyboardButton("📅 Ежемесячное", callback_data=f"setremrepeat_{rid}_monthly")],
            [InlineKeyboardButton("🎂 Ежегодное", callback_data=f"setremrepeat_{rid}_yearly")],
            [InlineKeyboardButton("◀️ Назад", callback_data=f"viewrem_{rid}")],
        ]))
        return True

    if data.startswith("setremrepeat_"):
        _, rid_str, repeat_type = data.split("_")
        rid = int(rid_str)
        item = _find_memory_reminder(chat_id, rid)
        if item:
            item["repeat_type"] = repeat_type
            _cancel_reminder_job(chat_id, rid)
            fire_at = item["time"]
            minutes = item.get("minutes", 0)
            if item.get("delivered") and repeat_type != "none":
                fire_at = next_repeat_time(fire_at, repeat_type, minutes=minutes) or fire_at
                item["time"] = fire_at
                item["delivered"] = False
            if not item.get("delivered"):
                _schedule_reminder(context.job_queue, chat_id, rid, item["text"], fire_at, item.get("is_timer", False), repeat_type, minutes=minutes)
            await db_update_reminder(chat_id, rid, repeat_type=repeat_type, fire_at=fire_at, delivered=item.get("delivered", False), minutes=minutes)
            await asyncio.to_thread(auto_assign_reminder_tags, chat_id, rid, repeat_type)
        await show_reminder_detail(query, chat_id, rid)
        return True

    # Timers
    if data == "open_timers":
        await show_timers_ui(query, chat_id)
        return True

    if data == "add_timer":
        start_process(user.id, chat_id, "timer", {"step": "waiting_time"}, query.message.message_id)
        await query.edit_message_text(_pad("⏱ Введи время таймера в минутах:\n\n• *10* — 10 минут\n• *60* — 1 час"), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[btn_cancel()]]))
        return True

    if data.startswith("deltimer_"):
        rid = int(data.split("_")[1])
        target = next((r for r in reminders.get(chat_id, []) if r["id"] == rid), None)
        if not target:
            await query.answer("❌ Таймер не найден", show_alert=True)
            return True

        # Показываем подтверждение удаления
        await query.edit_message_text(
            f"🗑 Удалить таймер?\n\n{target['text']}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Да, удалить", callback_data=f"confirmdeltimer_{rid}")],
                [InlineKeyboardButton("◀️ Назад", callback_data="timers_mode_delete"), btn_menu()],
            ])
        )
        return True

    if data.startswith("confirmdeltimer_"):
        rid = int(data.split("_")[1])
        items = reminders.get(chat_id, [])
        target = next((r for r in items if r["id"] == rid), None)
        if target and "job" in target:
            target["job"].schedule_removal()
            reminders[chat_id] = [r for r in items if r["id"] != rid]
        await db_delete_reminder(chat_id, rid)
        try:
            await bot.delete_message(chat_id=chat_id, message_id=query.message.message_id)
        except Exception:
            pass
        await show_timers_ui(query, chat_id, bot=bot, user_id=user.id)
        return True

    # Режим удаления таймеров
    if data == "timers_mode_delete":
        items = [r for r in reminders.get(chat_id, []) if r.get("is_timer")]
        if not items:
            await query.edit_message_text(_pad("📭 Таймеров нет."), reply_markup=InlineKeyboardMarkup([[btn_menu()]]))
            return True
        keyboard = []
        for r in items:
            remaining = max(0, int((r["time"] - datetime.now()).total_seconds()))
            mins, secs = divmod(remaining, 60)
            remaining_str = f"{mins}м {secs}с" if mins else f"{secs}с"
            keyboard.append([InlineKeyboardButton(f"🗑 {remaining_str} — {r['text'][:25]}", callback_data=f"deltimer_{r['id']}")])
        keyboard.append([
            InlineKeyboardButton("✚ Добавить", callback_data="add_timer"),
            InlineKeyboardButton("✅ Готово", callback_data="open_timers"),
        ])
        keyboard.append([btn_menu()])
        await query.edit_message_text(_pad("🗑 *Выбери таймер для удаления:*"), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        return True

    if data.startswith("viewtimer_"):
        rid = int(data.split("_")[1])
        target = next((r for r in reminders.get(chat_id, []) if r["id"] == rid), None)
        if not target:
            await query.answer("❌ Таймер не найден", show_alert=True)
            return True
        remaining = max(0, int((target["time"] - datetime.now()).total_seconds()))
        mins, secs = divmod(remaining, 60)
        remaining_str = f"{mins}м {secs}с" if mins else f"{secs}с"
        await query.edit_message_text(
            f"⏱ *Таймер*\n\nОсталось: {remaining_str}\n\n{target['text']}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✏️ Название", callback_data=f"edittimername_{rid}"), InlineKeyboardButton("✏️ Время", callback_data=f"edittimertime_{rid}")],
                [InlineKeyboardButton("◀️ Назад", callback_data="open_timers"), btn_menu()],
            ])
        )
        return True

    if data.startswith("edittimername_"):
        rid = int(data.split("_")[1])
        start_process(user.id, chat_id, "edit_timer_name", {"step": "waiting_name", "rid": rid}, query.message.message_id)
        await query.edit_message_text(_pad("✏️ Введи новое название таймера:"), reply_markup=InlineKeyboardMarkup([[btn_cancel()]]))
        return True

    if data.startswith("edittimertime_"):
        rid = int(data.split("_")[1])
        start_process(user.id, chat_id, "edit_timer_time", {"step": "waiting_time", "rid": rid}, query.message.message_id)
        await query.edit_message_text(_pad("⏱ Введи новое время таймера в минутах:\n\n• *10* — 10 минут\n• *60* — 1 час"), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[btn_cancel()]]))
        return True

    return False
