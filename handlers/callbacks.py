"""Callback button handler."""
import asyncio
import calendar
import logging

from telegram import InlineKeyboardMarkup

from db import (
    db_get_lists_for_user, db_get_items, db_get_list,
    db_delete_item_by_index, db_delete_list, db_get_summa,
    db_delete_reminder, db_update_reminder, db_get_reminder,
)
from handlers.session import (
    register_message, start_process, finish_process,
    processes, reminders, main_menu_messages, _store_memory_reminder,
)
from handlers.reminders import (
    _cancel_reminder_job, _find_memory_reminder, _remove_memory_reminder,
    _schedule_reminder, _row_to_reminder, show_reminders_ui,
    show_reminder_detail, show_timers_ui, next_reminder_id,
)
from keyboards import btn_menu, show_main_menu
from utils.time_utils import (
    parse_reminder_time_arg, next_daily_at, next_monthly_at,
    next_yearly_at, parse_clock, describe_when, _repeat_icon, _repeat_label,
)
from ai import _fetch_rub_direct, history_clear

logger = logging.getLogger(__name__)


async def button_handler(update, context):
    query = update.callback_query
    await query.answer()
    data = query.data
    user = query.from_user
    chat_id = query.message.chat_id
    bot = context.bot

    register_message(user.id, chat_id, query.message.message_id)

    # ── Status OK ────────────────────────────────────────────────────────────
    if data.startswith("status_ok_"):
        try:
            command_message_id = int(data.split("_")[2])
        except (IndexError, ValueError):
            command_message_id = 0
        for msg_id in (query.message.message_id, command_message_id):
            if not msg_id:
                continue
            try:
                await bot.delete_message(chat_id=chat_id, message_id=msg_id)
            except Exception as e:
                logger.debug(f"Не удалось удалить status-сообщение {msg_id}: {e}")
        return

    # ── Menu / Cancel ───────────────────────────────────────────────────────────
    if data == "go_menu":
        await finish_process(bot, user.id, show_menu=False)
        main_menu_messages[user.id] = query.message.message_id
        await show_main_menu(bot, user.id)
        return

    # ── Rub rate ───────────────────────────────────────────────────────────────
    if data == "open_rub":
        msg = await bot.send_message(chat_id=chat_id, text="💱 Получаю курс рубля...")
        register_message(user.id, chat_id, msg.message_id)
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(_fetch_rub_direct, db_get_summa(user.id)),
                timeout=15.0
            )
            await bot.edit_message_text(
                chat_id=chat_id, message_id=msg.message_id,
                text=result, parse_mode="Markdown"
            )
        except asyncio.TimeoutError:
            await bot.edit_message_text(
                chat_id=chat_id, message_id=msg.message_id,
                text="⏰ Сайт не ответил вовремя."
            )
        except Exception as e:
            logger.error(f"Rub error: {e}")
            await bot.edit_message_text(
                chat_id=chat_id, message_id=msg.message_id,
                text="⚠️ Не удалось получить курс."
            )
        asyncio.create_task(_auto_cleanup(bot, user.id, chat_id, msg.message_id, delay=30))
        return

    # ── Reminders ──────────────────────────────────────────────────────────────
    if data == "open_reminders":
        await show_reminders_ui(query, chat_id)
        return

    if data == "add_reminder":
        start_process(user.id, chat_id, "reminder", {"step": "waiting_repeat"}, query.message.message_id)
        await query.edit_message_text(
            "⏰ Выбери тип напоминания:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔔 Одноразовое", callback_data="remtype_none")],
                [InlineKeyboardButton("🔁 Ежедневное", callback_data="remtype_daily")],
                [InlineKeyboardButton("📅 Ежемесячное", callback_data="remtype_monthly")],
                [InlineKeyboardButton("🎂 Ежегодное", callback_data="remtype_yearly")],
                [btn_cancel()],
            ])
        )
        return

    if data.startswith("remtype_"):
        repeat_type = data.split("_", 1)[1]
        if user.id not in processes or processes[user.id]["type"] != "reminder":
            start_process(user.id, chat_id, "reminder", {"step": "waiting_time"}, query.message.message_id)
        first_steps = {
            "none": "waiting_time",
            "daily": "waiting_time",
            "monthly": "waiting_month_day",
            "yearly": "waiting_year_date"
        }
        processes[user.id]["state"] = {"step": first_steps[repeat_type], "repeat_type": repeat_type}
        prompts = {
            "none": "Введи время:\n\n• *14:30* — сегодня\n• *завтра 14:30*\n• *25.05 14:30*\n• *1h30m* — через промежуток",
            "daily": "Введи время ежедневного напоминания:\n\n• *07:30*",
            "monthly": "Введи число месяца:\n\n• *5* — каждый месяц 5 числа\n• *31* — в коротких месяцах последний день",
            "yearly": "Введи дату:\n\n• *12.08* — каждый год 12 августа",
        }
        await query.edit_message_text(
            f"{_repeat_icon(repeat_type)} Тип: *{md(_repeat_label(repeat_type))}*\n\n{prompts[repeat_type]}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        return

    if data.startswith("viewrem_"):
        await show_reminder_detail(query, chat_id, int(data.split("_")[1]))
        return

    if data.startswith("delrem_"):
        rid = int(data.split("_")[1])
        _cancel_reminder_job(chat_id, rid)
        _remove_memory_reminder(chat_id, rid)
        await asyncio.to_thread(db_delete_reminder, chat_id, rid)
        await show_reminders_ui(query, chat_id)
        return

    if data.startswith("snooze_"):
        _, rid_str, amount = data.split("_")
        rid = int(rid_str)
        delta = {"10m": timedelta(minutes=10), "1h": timedelta(hours=1), "1d": timedelta(days=1)}.get(amount)
        item = _find_memory_reminder(chat_id, rid)
        if not item:
            row = await asyncio.to_thread(db_get_reminder, chat_id, rid)
            item = _row_to_reminder(row) if row else None
        if item and delta:
            new_time = datetime.now() + delta
            _cancel_reminder_job(chat_id, rid)
            item["time"] = new_time
            item["delivered"] = False
            _schedule_reminder(
                context.job_queue, chat_id, rid, item["text"], new_time,
                item.get("is_timer", False), item.get("repeat_type", "none")
            )
            await asyncio.to_thread(db_update_reminder, chat_id, rid, fire_at=new_time, delivered=False)
        await show_reminder_detail(query, chat_id, rid)
        return

    if data.startswith("editremtext_"):
        rid = int(data.split("_")[1])
        start_process(user.id, chat_id, "edit_reminder", {"step": "waiting_text", "rid": rid}, query.message.message_id)
        await query.edit_message_text(
            "✏️ Введи новый текст напоминания:",
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        return

    if data.startswith("editremtime_"):
        rid = int(data.split("_")[1])
        item = _find_memory_reminder(chat_id, rid)
        repeat_type = (item or {}).get("repeat_type", "none")
        first_steps = {"monthly": "waiting_month_day", "yearly": "waiting_year_date"}
        step = first_steps.get(repeat_type, "waiting_time")
        start_process(user.id, chat_id, "edit_reminder", {"step": step, "rid": rid, "repeat_type": repeat_type}, query.message.message_id)
        prompts = {
            "monthly": "🕒 Введи новое число месяца:",
            "yearly": "🕒 Введи новую дату в формате *дд.мм*:",
        }
        await query.edit_message_text(
            prompts.get(repeat_type, f"🕒 Введи новое время для типа *{md(_repeat_label(repeat_type))}*:"),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        return

    if data.startswith("editremrepeat_"):
        rid = int(data.split("_")[1])
        await query.edit_message_text(
            "🔁 Выбери новый тип повтора:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔔 Одноразовое", callback_data=f"setremrepeat_{rid}_none")],
                [InlineKeyboardButton("🔁 Ежедневное", callback_data=f"setremrepeat_{rid}_daily")],
                [InlineKeyboardButton("📅 Ежемесячное", callback_data=f"setremrepeat_{rid}_monthly")],
                [InlineKeyboardButton("🎂 Ежегодное", callback_data=f"setremrepeat_{rid}_yearly")],
                [InlineKeyboardButton("◀️ Назад", callback_data=f"viewrem_{rid}")],
            ])
        )
        return

    if data.startswith("setremrepeat_"):
        _, rid_str, repeat_type = data.split("_")
        rid = int(rid_str)
        item = _find_memory_reminder(chat_id, rid)
        if item:
            item["repeat_type"] = repeat_type
            _cancel_reminder_job(chat_id, rid)
            fire_at = item["time"]
            if item.get("delivered") and repeat_type != "none":
                from utils.time_utils import next_repeat_time
                fire_at = next_repeat_time(fire_at, repeat_type) or fire_at
                item["time"] = fire_at
                item["delivered"] = False
            if not item.get("delivered"):
                _schedule_reminder(
                    context.job_queue, chat_id, rid, item["text"], fire_at,
                    item.get("is_timer", False), repeat_type
                )
            await asyncio.to_thread(
                db_update_reminder, chat_id, rid,
                repeat_type=repeat_type, fire_at=fire_at, delivered=item.get("delivered", False)
            )
        await show_reminder_detail(query, chat_id, rid)
        return

    # ── Timers ───────────────────────────────────────────────────────────────────
    if data == "open_timers":
        await show_timers_ui(query, chat_id)
        return

    if data == "add_timer":
        start_process(user.id, chat_id, "timer", {"step": "waiting_time"}, query.message.message_id)
        await query.edit_message_text(
            "⏱ Введи время таймера:\n\n"
            "• *300* — секунды\n"
            "• *5m* — минуты\n"
            "• *1h30m* — часы и минуты",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        return

    if data.startswith("deltimer_"):
        rid = int(data.split("_")[1])
        items = reminders.get(chat_id, [])
        target = next((r for r in items if r["id"] == rid), None)
        if target and "job" in target:
            target["job"].schedule_removal()
            reminders[chat_id] = [r for r in items if r["id"] != rid]
        await asyncio.to_thread(db_delete_reminder, chat_id, rid)
        await show_timers_ui(query, chat_id)
        return

    # ── Summa ──────────────────────────────────────────────────────────────────
    if data == "open_summa":
        summa = db_get_summa(user.id)
        if summa is not None:
            text = f"💰 *Текущая сумма:* {int(summa):,} сум".replace(",", " ")
            keyboard = [
                [InlineKeyboardButton("✏️ Изменить", callback_data="change_summa")],
                [btn_menu()]
            ]
        else:
            text = "💰 Сумма не задана. Введи сумму (в сумах):"
            keyboard = [[btn_cancel()]]
            start_process(user.id, chat_id, "summa", {"step": "waiting_summa"}, query.message.message_id)
        await query.edit_message_text(
            text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if data == "change_summa":
        start_process(user.id, chat_id, "summa", {"step": "waiting_summa"}, query.message.message_id)
        await query.edit_message_text(
            "✏️ Введи новую сумму (в сумах):",
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        return

    # ── Search ──────────────────────────────────────────────────────────────────
    if data == "open_search":
        start_process(user.id, chat_id, "search", {"step": "waiting_query"}, query.message.message_id)
        await query.edit_message_text(
            "🔍 Введи запрос для поиска:",
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        return

    # ── Clean ──────────────────────────────────────────────────────────────────
    if data == "do_clean":
        history_clear(user.id)
        try:
            await bot.delete_message(chat_id=chat_id, message_id=query.message.message_id)
            if main_menu_messages.get(user.id) == query.message.message_id:
                main_menu_messages.pop(user.id, None)
        except Exception:
            pass
        for i in range(1, 10):
            try:
                msg_id = query.message.message_id - i
                await bot.delete_message(chat_id=chat_id, message_id=msg_id)
                if main_menu_messages.get(user.id) == msg_id:
                    main_menu_messages.pop(user.id, None)
            except Exception:
                pass
        if user.id in processes:
            del processes[user.id]
        await show_main_menu(bot, user.id, "🧹 Чистота! История диалога очищена.")
        return

    # ── Lists ───────────────────────────────────────────────────────────────────
    if data in ("open_my_lists", "back_to_lists"):
        lists = await asyncio.to_thread(db_get_lists_for_user, user.id)
        keyboard = []
        for lst in lists:
            items = await asyncio.to_thread(db_get_items, lst["list_id"])
            label = f"📋 {lst['name']} ({len(items)})" if items else f"📋 {lst['name']} (пуст)"
            keyboard.append([InlineKeyboardButton(label, callback_data=f"openlist_{lst['list_id']}")])
        keyboard.append([InlineKeyboardButton("➕ Добавить список", callback_data="newlist_personal")])
        keyboard.append([btn_menu()])
        text = "📋 *Твои списки:*" if lists else "📭 Списков пока нет"
        await query.edit_message_text(
            text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if data == "newlist_personal":
        start_process(user.id, chat_id, "list", {"step": "creating_list_name"}, query.message.message_id)
        await query.edit_message_text(
            "✏️ Введи название списка:",
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        return

    if data.startswith("openlist_"):
        await _show_list_menu(query, data[9:])
        return

    if data.startswith("viewitems_"):
        await _show_list_items(query, data[10:])
        return

    if data.startswith("additem_"):
        list_id = data[8:]
        lst = await asyncio.to_thread(db_get_list, list_id)
        name = lst["name"] if lst else list_id
        if user.id not in processes or processes[user.id]["type"] != "list":
            start_process(user.id, chat_id, "list", {}, query.message.message_id)
        processes[user.id]["state"] = {
            "step": "adding_items",
            "list_id": list_id,
            "list_name": name
        }
        await query.edit_message_text(
            f"➕ Добавляю в *{md(name)}*\n\nОтправляй элементы по одному.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Завершить ввод", callback_data=f"done_adding_{list_id}")],
                [btn_cancel()],
            ])
        )
        return

    if data.startswith("done_adding_"):
        list_id = data[12:]
        if user.id in processes:
            proc = processes[user.id]
            chat_id_proc = proc.get("chat_id", chat_id)
            for msg_id in proc.get("messages", []):
                try:
                    await bot.delete_message(chat_id=chat_id_proc, message_id=msg_id)
                except Exception:
                    pass
            del processes[user.id]

        lst = await asyncio.to_thread(db_get_list, list_id)
        items = await asyncio.to_thread(db_get_items, list_id)
        name = lst["name"] if lst else list_id

        keyboard = []
        for i, item in enumerate(items):
            keyboard.append([InlineKeyboardButton(
                f"✕ {item.get('item', '')}",
                callback_data=f"delitem_{list_id}_{i}"
            )])
        keyboard.append([InlineKeyboardButton("➕ Добавить", callback_data=f"additem_{list_id}")])
        keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data=f"openlist_{list_id}"), btn_menu()])

        safe_name = md(name)
        text_out = f"📋 *{safe_name}:*\n_нажми на элемент чтобы удалить_" if items else f"📋 *{safe_name}* — пуст."
        try:
            await query.edit_message_text(
                text_out, parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception:
            await bot.send_message(
                chat_id=chat_id, text=text_out, parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        await show_main_menu(bot, user.id, "✅ Готово!")
        return

    if data.startswith("delitem_"):
        parts = data.split("_")
        list_id = parts[1]
        index = int(parts[2])
        await asyncio.to_thread(db_delete_item_by_index, list_id, index)
        await _show_list_items(query, list_id)
        return

    if data.startswith("dellist_"):
        list_id = data[8:]
        lst = await asyncio.to_thread(db_get_list, list_id)
        await query.edit_message_text(
            f"🗑 Удалить список *{md(lst['name'] if lst else list_id)}*?\nВсе элементы будут удалены.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Да, удалить", callback_data=f"confirmdellist_{list_id}")],
                [InlineKeyboardButton("❌ Отмена", callback_data=f"openlist_{list_id}")],
            ])
        )
        return

    if data.startswith("confirmdellist_"):
        list_id = data[15:]
        lst = await asyncio.to_thread(db_get_list, list_id)
        name = lst["name"] if lst else list_id
        await asyncio.to_thread(db_delete_list, list_id)
        try:
            await bot.delete_message(chat_id=chat_id, message_id=query.message.message_id)
            if main_menu_messages.get(user.id) == query.message.message_id:
                main_menu_messages.pop(user.id, None)
        except Exception as e:
            logger.debug(f"Не удалось удалить подтверждение: {e}")
        await show_main_menu(bot, user.id, f"🗑 Список *{md(name)}* удалён.")
        return


# ─── List helpers ─────────────────────────────────────────────────────────────

async def _show_list_menu(query, list_id: str):
    lst = await asyncio.to_thread(db_get_list, list_id)
    if not lst:
        await query.edit_message_text("❌ Список не найден.")
        return
    items = await asyncio.to_thread(db_get_items, list_id)
    count_str = f" ({len(items)})" if items else " (пуст)"
    await query.edit_message_text(
        f"📋 *{md(lst['name'])}*{count_str}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📖 Открыть", callback_data=f"viewitems_{list_id}")],
            [InlineKeyboardButton("➕ Добавить", callback_data=f"additem_{list_id}")],
            [InlineKeyboardButton("🗑 Удалить список", callback_data=f"dellist_{list_id}")],
            [InlineKeyboardButton("◀️ Назад", callback_data="open_my_lists"), btn_menu()],
        ])
    )


async def _show_list_items(query, list_id: str):
    lst = await asyncio.to_thread(db_get_list, list_id)
    items = await asyncio.to_thread(db_get_items, list_id)
    name = lst["name"] if lst else list_id

    if not items:
        await query.edit_message_text(
            f"📋 *{md(name)}* — пуст.\n\nНажми ➕ чтобы добавить элементы.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Добавить", callback_data=f"additem_{list_id}")],
                [InlineKeyboardButton("◀️ Назад", callback_data=f"openlist_{list_id}"), btn_menu()],
            ])
        )
        return

    keyboard = []
    for i, item in enumerate(items):
        keyboard.append([InlineKeyboardButton(
            f"✕ {item.get('item', '')}",
            callback_data=f"delitem_{list_id}_{i}"
        )])
    keyboard.append([InlineKeyboardButton("➕ Добавить", callback_data=f"additem_{list_id}")])
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data=f"openlist_{list_id}"), btn_menu()])

    await query.edit_message_text(
        f"📋 *{md(name)}:*\n_нажми на элемент чтобы удалить_",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def _auto_cleanup(bot, user_id: int, chat_id: int, message_id: int, delay: int = 5):
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass


def md(text: str) -> str:
    from telegram.helpers import escape_markdown
    return escape_markdown(str(text), version=1)


from datetime import datetime, timedelta
from telegram import InlineKeyboardButton
