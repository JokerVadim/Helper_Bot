"""Birthdays domain processor.

Отдельный раздел "Дни рождения" со своим UI (как у напоминаний),
своей системой уведомлений и настройкой времени.
"""
import asyncio
import logging
import re
from datetime import datetime, date, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from db import (
    db_get_birthdays, db_save_birthday, db_delete_birthday, db_birthday_exists,
    db_get_birthday_time, db_set_birthday_time,
    db_update_birthday,
)
from keyboards import btn_menu, btn_cancel, show_main_menu
from handlers.session import register_message, start_process, finish_process
from handlers.processors import register_message_handler, register_callback_handler
from utils import md, _pad

logger = logging.getLogger(__name__)

_notified_birthdays_today: set = set()
_bday_preview: dict[int, dict | None] = {}
_bday_preview_task: dict[int, asyncio.Task | None] = {}


def _set_bday_preview(user_id: int, bday: dict | None):
    if bday:
        _bday_preview[user_id] = {"name": bday["name"], "birth_date": bday["birth_date"]}
    else:
        _bday_preview.pop(user_id, None)


async def _auto_hide_bday_preview(user_id: int, chat_id: int, message_id: int, bot):
    """Скрыть превью дня рождения через 5 секунд."""
    await asyncio.sleep(5)
    if user_id in _bday_preview:
        _bday_preview.pop(user_id, None)
        _bday_preview_task[user_id] = None
        text, keyboard = await _build_birthdays_content(user_id)
        try:
            await bot.edit_message_text(
                text, parse_mode="Markdown",
                chat_id=chat_id, message_id=message_id,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception:
            pass

# ─── Action Mode ──────────────────────────────────────────────────────────────
_bday_action_modes: dict[int, str] = {}

def _get_bday_action_mode(user_id: int) -> str:
    return _bday_action_modes.get(user_id, "")

def _set_bday_action_mode(user_id: int, mode: str):
    if mode:
        _bday_action_modes[user_id] = mode
    else:
        _bday_action_modes.pop(user_id, None)


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════

MONTH_NAMES = {
    1: "Января", 2: "Февраля", 3: "Марта", 4: "Апреля",
    5: "Мая", 6: "Июня", 7: "Июля", 8: "Августа",
    9: "Сентября", 10: "Октября", 11: "Ноября", 12: "Декабря",
}

MONTH_GENITIVE = {
    1: "Января", 2: "Февраля", 3: "Марта", 4: "Апреля",
    5: "Мая", 6: "Июня", 7: "Июля", 8: "Августа",
    9: "Сентября", 10: "Октября", 11: "Ноября", 12: "Декабря",
}


def parse_birthday_line(line: str) -> tuple[str, str] | None:
    """Парсит строку вида 'Имя|ДД.ММ.ГГГГ' или 'Имя|ДД.ММ'.

    Возвращает (имя, ДД.ММ) или (имя, ДД.ММ.ГГГГ), или None.
    """
    line = line.strip()
    if not line or "|" not in line:
        return None

    parts = line.split("|", 1)
    name = parts[0].strip()
    date_str = parts[1].strip()

    if not name or not date_str:
        return None

    m = re.fullmatch(r'(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?', date_str)
    if not m:
        return None

    day, month = int(m.group(1)), int(m.group(2))
    if day < 1 or day > 31 or month < 1 or month > 12:
        return None

    # Если указан год — сохраняем, иначе только день.месяц
    if m.group(3):
        return name, f"{day:02d}.{month:02d}.{m.group(3)}"
    return name, f"{day:02d}.{month:02d}"


def parse_birthday_multiline(text: str) -> list[tuple[str, str]]:
    """Парсит многострочный список дней рождения."""
    results = []
    for line in text.split("\n"):
        parsed = parse_birthday_line(line)
        if parsed:
            results.append(parsed)
    return results


def _sort_birthdays(birthdays: list[dict]) -> list[dict]:
    """Сортирует дни рождения по месяцу и дню."""
    def sort_key(b):
        parts = b["birth_date"].split(".")
        return int(parts[1]), int(parts[0])
    return sorted(birthdays, key=sort_key)


def _calc_age(birth_date: str) -> int | None:
    """Вычисляет текущий возраст. Если год не указан — None."""
    parts = birth_date.split(".")
    if len(parts) < 3:
        return None
    try:
        bd = datetime.strptime(birth_date, "%d.%m.%Y")
        today = datetime.now()
        age = today.year - bd.year
        if (today.month, today.day) < (bd.month, bd.day):
            age -= 1
        return age
    except (ValueError, IndexError):
        return None


def _days_until_next_birthday(birth_date: str) -> int | None:
    """Возвращает количество дней до следующего дня рождения."""
    parts = birth_date.split(".")
    if len(parts) < 2:
        return None
    day, month = int(parts[0]), int(parts[1])
    today = date.today()
    try:
        next_bday = date(today.year, month, day)
    except ValueError:
        return None
    if next_bday < today:
        try:
            next_bday = date(today.year + 1, month, day)
        except ValueError:
            return None
    return (next_bday - today).days


def _format_bday_short(name: str, birth_date: str) -> str:
    """Форматирует: 🎂 Имя — 15 Марта (39 / 297)

    Первое число — текущий возраст (если есть год), иначе ?.
    Второе — дней до следующего ДР (🎉 если сегодня).
    """
    parts = birth_date.split(".")
    if len(parts) < 2:
        return f"🎂 {name}"
    day, month = int(parts[0]), int(parts[1])
    month_name = MONTH_NAMES.get(month, "")

    result = f"🎂 {name} — {day} {month_name}"

    age = _calc_age(birth_date)
    days = _days_until_next_birthday(birth_date)

    age_str = str(age) if age is not None else "?"
    days_str = "🎉" if days == 0 else str(days or "?")

    result += f" ({age_str} / {days_str})"

    return result


def _format_bday_detail(name: str, birth_date: str) -> str:
    """Форматирует детальную информацию о дне рождения."""
    parts = birth_date.split(".")
    day, month = int(parts[0]), int(parts[1])
    month_name = MONTH_NAMES.get(month, "")
    lines = [f"🎂 *{md(name)}*", f"📅 {day} {month_name}"]

    age = _calc_age(birth_date) if len(parts) >= 3 else None
    days = _days_until_next_birthday(birth_date)
    if days is None:
        days = 0

    if age is not None:
        lines.append(f"сейчас *{age}* лет")
        if days == 0:
            lines.append("🎉 *Сегодня!*")
        else:
            lines.append(f"через {days} дн., исполнится *{age + 1}*")
    else:
        if days == 0:
            lines.append("🎉 *Сегодня!*")
        else:
            lines.append(f"через {days} дн.")

    return _pad("\n".join(lines))


# ═══════════════════════════════════════════════════════════════════════════════
# Birthday notification system (independent from reminders)
# ═══════════════════════════════════════════════════════════════════════════════

def _get_birthdays_for_delta(days: int = 0) -> list[dict]:
    """Возвращает дни рождения, у которых дата смещена на days от сегодня.

    days=0  — сегодняшние
    days=1  — завтрашние
    days=-1 — вчерашние

    Результат: список dict-ов {user_id, name, birth_date, id}.
    """
    from db import db
    target = datetime.now() + timedelta(days=days)
    target_str = f"{target.day:02d}.{target.month:02d}"
    results = []

    user_ids = db.get_all_birthday_user_ids()
    for uid in user_ids:
        bdays = db.get_birthdays(uid)
        for b in bdays:
            bd = b["birth_date"].split(".")
            if len(bd) >= 2:
                bd_short = f"{int(bd[0]):02d}.{int(bd[1]):02d}"
                if bd_short == target_str:
                    results.append({
                        "user_id": uid,
                        "name": b["name"],
                        "birth_date": b["birth_date"],
                        "id": b["id"],
                    })

    return results


async def check_birthdays(app):
    """Проверка дней рождения. Вызывается каждые 60 секунд из bot.py.

    Отправляет:
    - Поздравление в день рождения (в заданное время notify_time, точное HH:MM)
    - Предупреждение за 1 день (в то же время, если notify_advance включено)
    """
    now = datetime.now()
    today = now.date()
    if today != getattr(check_birthdays, '_last_check_date', None):
        _notified_birthdays_today.clear()
        check_birthdays._last_check_date = today

    # ── 1. Сегодняшние дни рождения (поздравление) ──
    today_bdays = await asyncio.to_thread(_get_birthdays_for_delta, 0)
    for bday in today_bdays:
        user_id = bday["user_id"]
        name = bday["name"]
        birth_date = bday["birth_date"]

        notify_time_str = await db_get_birthday_time( user_id)
        try:
            notify_hour, notify_minute = map(int, notify_time_str.split(":"))
        except (ValueError, TypeError):
            notify_hour, notify_minute = 10, 0

        # Точная проверка HH:MM — не отправляем в неверную минуту
        if now.hour != notify_hour or now.minute != notify_minute:
            continue
        # Note: 60-second scheduler limitation — may miss exact minute on busy loads

        if (user_id, bday["id"]) in _notified_birthdays_today:
            continue

        age = _calc_age(birth_date)
        age_text = f" — *{age} лет*! 🎉" if age is not None else "! 🎉"

        parts = birth_date.split(".")
        day, month = int(parts[0]), int(parts[1])
        month_name = MONTH_NAMES.get(month, "")

        text = _pad(
            f"🎂 *Сегодня день рождения!* 🎂\n\n"
            f"{name} — {day} {month_name}{age_text}\n\n"
            f"Поздравь именинника! 🎉🎊"
        )

        try:
            msg = await app.bot.send_message(chat_id=user_id, text=text, parse_mode="Markdown")
            register_message(user_id, user_id, msg.message_id)
            logger.info(f"🎂 Birthday notification sent to {user_id} for {name}")
            _notified_birthdays_today.add((user_id, bday["id"]))
        except Exception as e:
            logger.error(f"Failed to send birthday notification to {user_id}: {e}")

    # ── 2. Завтрашние дни рождения (предупреждение) ──
    advance_bdays = await asyncio.to_thread(_get_birthdays_for_delta, 1)
    for bday in advance_bdays:
        user_id = bday["user_id"]
        name = bday["name"]
        birth_date = bday["birth_date"]

        notify_time_str = await db_get_birthday_time( user_id)
        try:
            notify_hour, notify_minute = map(int, notify_time_str.split(":"))
        except (ValueError, TypeError):
            notify_hour, notify_minute = 10, 0

        # Точная проверка HH:MM
        if now.hour != notify_hour or now.minute != notify_minute:
            continue

        if (user_id, bday["id"]) in _notified_birthdays_today:
            continue

        parts = birth_date.split(".")
        day, month = int(parts[0]), int(parts[1])
        month_name = MONTH_NAMES.get(month, "")

        age = _calc_age(birth_date)
        age_text = f" — *{age} лет*" if age is not None else ""

        text = _pad(
            f"🎂 *Завтра день рождения!* 🎂\n\n"
            f"Завтра у *{md(name)}*{age_text}!\n"
            f"Дата: {day} {month_name}\n\n"
            f"Не забудь поздравить! 🎉🎊"
        )

        try:
            msg = await app.bot.send_message(chat_id=user_id, text=text, parse_mode="Markdown")
            register_message(user_id, user_id, msg.message_id)
            logger.info(f"🎂 Advance birthday notification sent to {user_id} for {name} (tomorrow)")
            _notified_birthdays_today.add((user_id, bday["id"]))
        except Exception as e:
            logger.error(f"Failed to send advance birthday notification to {user_id}: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# UI: Show birthdays list (like reminders UI)
# ═══════════════════════════════════════════════════════════════════════════════

async def _build_birthdays_content(user_id: int, custom_text: str = None) -> tuple[str, list]:
    """Построить текст и клавиатуру списка дней рождения."""
    birthdays = await db_get_birthdays(user_id)
    sorted_bdays = _sort_birthdays(birthdays)
    notify_time = await db_get_birthday_time(user_id)
    action_mode = _get_bday_action_mode(user_id)
    keyboard = []

    preview = _bday_preview.get(user_id)

    if not sorted_bdays:
        text = _pad("🎂 *Дни рождения*\n\nПока нет сохранённых дней рождения.")
    else:
        for b in sorted_bdays:
            is_active = preview and preview["name"] == b["name"] and preview["birth_date"] == b["birth_date"]
            if action_mode == "delete":
                label = _format_bday_short(b['name'], b['birth_date']).replace("🎂", "🗑", 1)
                keyboard.append([InlineKeyboardButton(label, callback_data=f"delbday_{b['id']}")])
            elif action_mode == "edit_name":
                label = _format_bday_short(b['name'], b['birth_date']).replace("🎂", "✏️", 1)
                keyboard.append([InlineKeyboardButton(label, callback_data=f"editbdayname_{b['id']}")])
            elif action_mode == "edit_date":
                label = _format_bday_short(b['name'], b['birth_date']).replace("🎂", "✏️", 1)
                keyboard.append([InlineKeyboardButton(label, callback_data=f"editbdaydate_{b['id']}")])
            else:
                label = _format_bday_short(b["name"], b["birth_date"])
                prefix = "👁 " if is_active else ""
                if is_active:
                    label = f"{prefix}{label}"
                keyboard.append([InlineKeyboardButton(label, callback_data=f"viewbday_{b['id']}")])

        text = "🎂 *Дни рождения:*"

    if preview:
        detail = _format_bday_detail(preview["name"], preview["birth_date"])
        text = detail

    delete_lbl = "✅ 🗑 Удалить" if action_mode == "delete" else "🗑 Удалить"
    name_lbl = "✅ ✏️ Имя" if action_mode == "edit_name" else "✏️ Имя"
    date_lbl = "✅ ✏️ Дата" if action_mode == "edit_date" else "✏️ Дата"
    keyboard.append([
        InlineKeyboardButton("✚ Добавить", callback_data="add_birthday"),
        InlineKeyboardButton(delete_lbl, callback_data="birthdaystogglemode_delete"),
    ])
    keyboard.append([
        InlineKeyboardButton(name_lbl, callback_data="birthdaystogglemode_edit_name"),
        InlineKeyboardButton(date_lbl, callback_data="birthdaystogglemode_edit_date"),
    ])
    keyboard.append([InlineKeyboardButton(f"⏰ Время ({notify_time})", callback_data="bday_time_edit"), btn_menu()])
    if action_mode:
        _labels = {"delete": "🗑 Удалить", "edit_name": "✏️ Имя", "edit_date": "✏️ Дата"}
        text += f"\n\n*Режим:* ✅ {_labels.get(action_mode, action_mode)}"

    if custom_text:
        text = custom_text

    return text, keyboard


async def _show_birthdays_list(query, custom_text: str = None, bot=None, user_id: int = None):
    """Показать список дней рождений. UI как у напоминаний."""
    user = query.from_user if query else None
    uid = user.id if user else user_id

    text, keyboard = await _build_birthdays_content(uid, custom_text)

    if bot and user_id:
        msg = await bot.send_message(chat_id=user_id, text=text, parse_mode="Markdown",
                               reply_markup=InlineKeyboardMarkup(keyboard))
        register_message(user_id, user_id, msg.message_id)
    else:
        await query.edit_message_text(text, parse_mode="Markdown",
                                      reply_markup=InlineKeyboardMarkup(keyboard))


# ═══════════════════════════════════════════════════════════════════════════════
# Callback Handlers
# ═══════════════════════════════════════════════════════════════════════════════

@register_callback_handler("open_birthdays")
async def cb_open_birthdays(query, context, data, user, chat_id, bot):
    """Открыть список дней рождения."""
    await _show_birthdays_list(query)


@register_callback_handler("add_birthday")
async def cb_add_birthday(query, context, data, user, chat_id, bot):
    """Начать добавление дня рождения."""
    start_process(user.id, chat_id, "birthday_add", {"step": "waiting_input"}, query.message.message_id)
    await query.edit_message_text(
        _pad("🎂 *Добавить день рождения*\n\n"
             "Отправь данные в формате:\n\n"
             "• `Имя|ДД.ММ.ГГГГ` — один человек\n"
             "• Или несколько строк:\n\n"
             "`Иван|15.03.1990`\n"
             "`Мария|22.07.1985`\n"
             "`Ольга|03.12`\n\n"
             "Год можно не указывать."),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
    )


@register_callback_handler("viewbday_")
async def cb_view_birthday(query, context, data, user, chat_id, bot):
    """Показать детали дня рождения (как превью карты, с авто-скрытием)."""
    bday_id = int(data.split("_")[1])
    birthdays = await db_get_birthdays(user.id)
    bday = next((b for b in birthdays if b["id"] == bday_id), None)
    if not bday:
        await query.answer("❌ Не найдено")
        return

    current = _bday_preview.get(user.id)
    if current and current["name"] == bday["name"] and current["birth_date"] == bday["birth_date"]:
        _set_bday_preview(user.id, None)
        if _bday_preview_task.get(user.id):
            _bday_preview_task[user.id].cancel()
            _bday_preview_task[user.id] = None
    else:
        _set_bday_preview(user.id, bday)
        if _bday_preview_task.get(user.id):
            _bday_preview_task[user.id].cancel()
        _bday_preview_task[user.id] = asyncio.create_task(
            _auto_hide_bday_preview(user.id, chat_id, query.message.message_id, bot)
        )

    text, keyboard = await _build_birthdays_content(user.id)
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))


@register_callback_handler("delbday_")
async def cb_del_birthday(query, context, data, user, chat_id, bot):
    """Подтверждение удаления дня рождения."""
    bday_id = int(data.split("_")[1])
    birthdays = await db_get_birthdays( user.id)
    bday = next((b for b in birthdays if b["id"] == bday_id), None)

    if not bday:
        await query.answer("❌ Запись не найдена", show_alert=True)
        return

    await query.edit_message_text(
        _pad(f"🗑 Удалить день рождения *{md(bday['name'])}*?"),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Да, удалить", callback_data=f"confirmdelbday_{bday_id}")],
            [InlineKeyboardButton("◀️ Назад", callback_data="open_birthdays"), btn_menu()],
        ])
    )


@register_callback_handler("confirmdelbday_")
async def cb_confirm_del_birthday(query, context, data, user, chat_id, bot):
    """Подтвердить удаление дня рождения."""
    bday_id = int(data.split("_")[1])
    birthdays = await db_get_birthdays( user.id)
    bday = next((b for b in birthdays if b["id"] == bday_id), None)
    name = bday["name"] if bday else ""

    if bday:
        await db_delete_birthday( user.id, bday_id)

    # Удаляем сообщение с подтверждением
    try:
        await bot.delete_message(chat_id=chat_id, message_id=query.message.message_id)
    except Exception:
        pass

    # Показываем обновлённый список новым сообщением
    await _show_birthdays_list(query, bot=bot, user_id=user.id,
                                custom_text=_pad(f"✅ *{md(name)}* удалён(а).") if name else None)


# TOGGLE режима удаления
@register_callback_handler("birthdaystogglemode_")
async def cb_birthdays_toggle_mode(query, context, data, user, chat_id, bot):
    """Переключить режим удаления (TOGGLE)."""
    mode = data.removeprefix("birthdaystogglemode_")
    current = _get_bday_action_mode(user.id)
    if current == mode:
        _set_bday_action_mode(user.id, "")
    else:
        _set_bday_action_mode(user.id, mode)
    await _show_birthdays_list(query)


# ─── Настройки времени уведомления ───────────────────────────────────────────

@register_callback_handler("bday_time_edit")
async def cb_bday_time_edit(query, context, data, user, chat_id, bot):
    """Изменить время уведомления."""
    start_process(user.id, chat_id, "birthday_time", {"step": "waiting_time"}, query.message.message_id)
    await query.edit_message_text(
        _pad("⏰ Введи новое время уведомления в формате *чч:мм*:\n\n"
             "• *10:00* — в 10 утра\n"
             "• *09:30* — в 9:30\n"
             "• *20:00* — в 8 вечера"),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
    )


# ─── Редактирование имени/даты ──────────────────────────────────────────────

@register_callback_handler("editbdayname_")
async def cb_edit_bday_name(query, context, data, user, chat_id, bot):
    """Изменить имя в дне рождения."""
    bday_id = int(data.split("_")[1])
    birthdays = await db_get_birthdays( user.id)
    bday = next((b for b in birthdays if b["id"] == bday_id), None)
    if not bday:
        await query.answer("❌ Запись не найдена", show_alert=True)
        return

    start_process(user.id, chat_id, "edit_birthday", {
        "step": "waiting_name",
        "bday_id": bday_id,
        "old_name": bday["name"],
        "old_date": bday["birth_date"],
    }, query.message.message_id)
    await query.edit_message_text(
        _pad(f"✏️ Введи новое имя для `{md(bday['name'])}`:"),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
    )


@register_callback_handler("editbdaydate_")
async def cb_edit_bday_date(query, context, data, user, chat_id, bot):
    """Изменить дату в дне рождения."""
    bday_id = int(data.split("_")[1])
    birthdays = await db_get_birthdays( user.id)
    bday = next((b for b in birthdays if b["id"] == bday_id), None)
    if not bday:
        await query.answer("❌ Запись не найдена", show_alert=True)
        return

    start_process(user.id, chat_id, "edit_birthday", {
        "step": "waiting_date",
        "bday_id": bday_id,
        "old_name": bday["name"],
        "old_date": bday["birth_date"],
    }, query.message.message_id)
    await query.edit_message_text(
        _pad(f"✏️ Введи новую дату для `{md(bday['name'])}` в формате:\n\n"
             "• `ДД.ММ.ГГГГ` — с годом\n"
             "• `ДД.ММ` — без года\n\n"
             f"Текущая дата: `{bday['birth_date']}`"),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
    )


@register_message_handler("edit_birthday")
async def handle_edit_birthday(update, context, proc, state):
    """Обработка редактирования дня рождения (имени или даты)."""
    from telegram import InlineKeyboardMarkup
    user = update.effective_user
    chat_id = update.effective_chat.id
    message = update.message or update.effective_message
    text = message.text.strip() if message.text else ""
    bot = context.bot
    register_message(user.id, chat_id, message.message_id)

    bday_id = state.get("bday_id")
    old_name = state.get("old_name", "")
    old_date = state.get("old_date", "")
    step = state.get("step")

    if step == "waiting_name":
        if not text:
            reply = await message.reply_text(
                _pad("✏️ Имя не может быть пустым. Введи новое имя:"),
                reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
            )
            register_message(user.id, chat_id, reply.message_id)
            return

        await db_update_birthday( user.id, bday_id, text, old_date)
        await finish_process(bot, user.id, show_menu=False)

        # Показываем обновлённый список
        # Имитируем открытие списка дней рождения
        birthdays = await db_get_birthdays( user.id)
        sorted_bdays = _sort_birthdays(birthdays)

        await show_main_menu(
            bot, user.id,
            _pad(f"✅ Имя изменено: *{md(old_name)}* → *{md(text)}*")
        )
        return

    if step == "waiting_date":
        parsed = parse_birthday_line(f"{old_name}|{text}")
        if not parsed:
            reply = await message.reply_text(
                _pad("❌ Не понял дату. Введи в формате:\n"
                     "• `ДД.ММ.ГГГГ` — например 15.03.1990\n"
                     "• `ДД.ММ` — например 15.03"),
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
            )
            register_message(user.id, chat_id, reply.message_id)
            return

        _, new_date = parsed
        await db_update_birthday( user.id, bday_id, old_name, new_date)
        await finish_process(bot, user.id, show_menu=False)

        await show_main_menu(
            bot, user.id,
            _pad(f"✅ Дата для *{md(old_name)}* изменена: *{old_date}* → *{new_date}*")
        )
        return








# ═══════════════════════════════════════════════════════════════════════════════
# Message Handlers
# ═══════════════════════════════════════════════════════════════════════════════

@register_message_handler("birthday_add")
async def handle_birthday_add_message(update, context, proc, state):
    """Обработка ввода данных дня рождения."""
    from telegram import InlineKeyboardMarkup
    user = update.effective_user
    chat_id = update.effective_chat.id
    message = update.message or update.effective_message
    text = message.text.strip() if message.text else ""
    bot = context.bot
    register_message(user.id, chat_id, message.message_id)

    step = state.get("step")

    if step == "waiting_input":
        if not text:
            reply = await message.reply_text(
                _pad("❌ Отправь данные в формате:\n\n"
                     "• `Имя|ДД.ММ.ГГГГ` — один человек\n"
                     "• Или несколько строк:\n\n"
                     "`Иван|15.03.1990`\n"
                     "`Мария|22.07.1985`"),
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
            )
            register_message(user.id, chat_id, reply.message_id)
            return

        birthdays = parse_birthday_multiline(text)

        if not birthdays:
            reply = await message.reply_text(
                _pad("❌ Не понял формат. Нужно:\n\n"
                     "• `Имя|ДД.ММ.ГГГГ`\n• Или несколько строк через Enter\n\n"
                     "`Иван|15.03`\n`Мария|22.07`"),
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
            )
            register_message(user.id, chat_id, reply.message_id)
            return

        created = 0
        skipped = 0
        added_names = []

        for name, birth_date in birthdays:
            exists = await db_birthday_exists( user.id, name)
            if exists:
                skipped += 1
                continue

            await db_save_birthday( user.id, name, birth_date)
            created += 1
            added_names.append(name)

        await finish_process(bot, user.id, show_menu=False)

        if created > 0:
            text_parts = ["🎂 *Дни рождения добавлены:*"]
            for name, bdate in birthdays[:created]:
                text_parts.append(f"• {_format_bday_short(name, bdate)}")
            text_parts.append(f"\n✅ Добавлено: {created}")
            if skipped:
                text_parts.append(f"⏭ Пропущено (уже есть): {skipped}")
            msg_text = _pad("\n".join(text_parts))
        else:
            msg_text = _pad("⚠️ Ничего не добавлено. Возможно, эти люди уже есть в списке.")

        await show_main_menu(bot, user.id, msg_text)


@register_message_handler("birthday_from_calendar")
async def handle_birthday_from_calendar(update, context, proc, state):
    """Обработка добавления дня рождения из календаря (дата уже выбрана)."""
    from telegram import InlineKeyboardMarkup
    user = update.effective_user
    chat_id = update.effective_chat.id
    message = update.message or update.effective_message
    text = message.text.strip() if message.text else ""
    bot = context.bot
    register_message(user.id, chat_id, message.message_id)

    step = state.get("step")
    prefilled_date = state.get("prefilled_date")

    if step == "waiting_name":
        if not text:
            reply = await message.reply_text(
                _pad("🎂 Имя не может быть пустым. Введи имя именинника:"),
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
            )
            register_message(user.id, chat_id, reply.message_id)
            return

        # Сохраняем имя, переходим к запросу года
        state["name"] = text
        state["step"] = "waiting_year"

        reply = await message.reply_text(
            _pad(f"🎂 Имя: *{md(text)}*\n\nВведи год рождения (например *1990*)\n\nИли *«-»* чтобы оставить без года:"),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        register_message(user.id, chat_id, reply.message_id)
        return

    if step == "waiting_year":
        name = state.get("name", "")
        if not name:
            await finish_process(bot, user.id, show_menu=True, menu_text="⚠️ Ошибка: имя не найдено.")
            return

        year_str = text.strip()
        if year_str == "-" or not year_str:
            birth_date = f"{prefilled_date.day:02d}.{prefilled_date.month:02d}"
        elif year_str.isdigit() and len(year_str) == 4:
            birth_date = f"{prefilled_date.day:02d}.{prefilled_date.month:02d}.{year_str}"
        else:
            reply = await message.reply_text(
                _pad("❌ Некорректный год. Введи 4 цифры (например *1990*)\n\nИли *«-»* чтобы оставить без года:"),
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
            )
            register_message(user.id, chat_id, reply.message_id)
            return

        exists = await db_birthday_exists( user.id, name)
        if exists:
            reply = await message.reply_text(
                _pad(f"⚠️ `{md(name)}` уже есть в списке дней рождения."),
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
            )
            register_message(user.id, chat_id, reply.message_id)
            return

        await db_save_birthday( user.id, name, birth_date)
        await finish_process(bot, user.id, show_menu=False)
        await show_main_menu(bot, user.id,
            _pad(f"🎂 *{md(name)}* добавлен(а) — {birth_date}!\n\n{_format_bday_short(name, birth_date)}")
        )


@register_message_handler("birthday_time")
async def handle_birthday_time_message(update, context, proc, state):
    """Обработка ввода времени уведомления."""
    from telegram import InlineKeyboardMarkup
    user = update.effective_user
    chat_id = update.effective_chat.id
    message = update.message or update.effective_message
    text = message.text.strip() if message.text else ""
    bot = context.bot
    register_message(user.id, chat_id, message.message_id)

    step = state.get("step")

    if step == "waiting_time":
        m = re.fullmatch(r'(\d{1,2}):(\d{2})', text.strip())
        if not m:
            reply = await message.reply_text(
                _pad("❌ Введи время в формате *чч:мм*:\n\n"
                     "• *10:00* — в 10 утра\n"
                     "• *14:30* — в 14:30"),
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
            )
            register_message(user.id, chat_id, reply.message_id)
            return

        hour, minute = int(m.group(1)), int(m.group(2))
        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            reply = await message.reply_text(
                _pad("❌ Неверное время. Введи в формате *чч:мм*."),
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
            )
            register_message(user.id, chat_id, reply.message_id)
            return

        time_str = f"{hour:02d}:{minute:02d}"
        await db_set_birthday_time( user.id, time_str)

        await finish_process(bot, user.id, show_menu=False)
        await _show_birthdays_list(None, bot=bot, user_id=user.id,
            custom_text=_pad(f"✅ Время уведомления о днях рождения изменено на *{time_str}*."))
