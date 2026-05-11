"""Command handlers."""
import asyncio
import logging
import uuid

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup

from db import (
    db_upsert_user, db_get_lists_for_user, db_get_items, db_get_list,
    db_create_list, db_add_item, db_delete_item_by_index, db_delete_list,
    db_get_summa, db_set_summa, db_get_reminder_counts, db_count_lists,
    db_count_users, db_get_pending_reminders, db_get_reminder,
    db_delete_reminder, db_update_reminder, db_save_reminder,
)
from handlers.session import (
    register_message, start_process, finish_process,
    processes, reminders, main_menu_messages, reminder_counter,
    _store_memory_reminder, _remove_memory_reminder,
)
from handlers.reminders import (
    next_reminder_id, _schedule_reminder, _cancel_reminder_job,
    _find_memory_reminder, _row_to_reminder, show_reminders_ui,
    show_reminder_detail, show_timers_ui,
)
from keyboards import btn_menu, btn_cancel, show_main_menu
from utils.time_utils import (
    parse_duration_seconds, next_repeat_time, parse_reminder_time_arg,
    parse_clock, next_daily_at, next_monthly_at, next_yearly_at,
    describe_when, parse_time_arg, _repeat_icon, _repeat_label,
)
from ai import (
    history_add, history_clear, do_search, _fetch_rub_direct,
    _ask_groq_with_history,
)
from shortcuts import SHORTCUTS
from config import MAX_SEARCH_RESULTS, MAX_CONTEXT_LENGTH

logger = logging.getLogger(__name__)


# ─── Commands ─────────────────────────────────────────────────────────────────

async def cmd_start(update, context):
    user = update.effective_user
    chat_id = update.effective_chat.id
    await asyncio.to_thread(db_upsert_user, user.id, user.first_name)
    if update.message:
        register_message(user.id, chat_id, update.message.message_id)
    await finish_process(context.bot, user.id, show_menu=True)


async def cmd_cancel(update, context):
    user = update.effective_user
    chat_id = update.effective_chat.id
    if update.message:
        register_message(user.id, chat_id, update.message.message_id)
    await finish_process(context.bot, user.id, show_menu=True, menu_text="✅ Действие отменено.")


async def cmd_status(update, context):
    user = update.effective_user
    chat_id = update.effective_chat.id
    command_message_id = update.message.message_id if update.message else 0
    if update.message:
        register_message(user.id, chat_id, update.message.message_id)
    counts = await asyncio.to_thread(db_get_reminder_counts)
    list_count = await asyncio.to_thread(db_count_lists)
    user_count = await asyncio.to_thread(db_count_users)
    active_process = processes.get(user.id, {}).get("type", "нет")

    text = (
        "✅ *Бот работает*\n\n"
        f"Напоминания:\n"
        f"• одноразовые: *{counts.get('once', 0)}*\n"
        f"• сработавшие: *{counts.get('delivered', 0)}*\n"
        f"• ежедневные: *{counts.get('daily', 0)}*\n"
        f"• ежемесячные: *{counts.get('monthly', 0)}*\n"
        f"• ежегодные: *{counts.get('yearly', 0)}*\n"
        f"• таймеры: *{counts.get('timers', 0)}*\n\n"
        f"Списки: *{list_count}*\n"
        f"Пользователи: *{user_count}*\n"
        f"Текущий процесс: *{md(active_process)}*\n"
        f"БД: `bot.db`"
    )
    await update.message.reply_text(
        text, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("OK", callback_data=f"status_ok_{command_message_id}")
        ]])
    )


async def cmd_addlist(update, context):
    user = update.effective_user
    chat_id = update.effective_chat.id
    await asyncio.to_thread(db_upsert_user, user.id, user.first_name)
    register_message(user.id, chat_id, update.message.message_id)
    start_process(user.id, chat_id, "list", {"step": "creating_list_name"}, update.message.message_id)
    msg = await update.message.reply_text(
        "✏️ Введи название нового списка:",
        reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
    )
    register_message(user.id, chat_id, msg.message_id)


async def cmd_showlists(update, context):
    user = update.effective_user
    chat_id = update.effective_chat.id
    await asyncio.to_thread(db_upsert_user, user.id, user.first_name)
    register_message(user.id, chat_id, update.message.message_id)
    lists = await asyncio.to_thread(db_get_lists_for_user, user.id)

    if not lists:
        msg = await update.message.reply_text("📭 Списков пока нет. Создай через /al")
        register_message(user.id, chat_id, msg.message_id)
        asyncio.create_task(_auto_cleanup(context.bot, user.id, chat_id, msg.message_id, delay=5))
        return

    keyboard = []
    for lst in lists:
        keyboard.append([InlineKeyboardButton(f"📋 {lst['name']}", callback_data=f"openlist_{lst['list_id']}")])
    msg = await update.message.reply_text(
        "📋 *Твои списки:*", parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    register_message(user.id, chat_id, msg.message_id)


async def cmd_done(update, context):
    user = update.effective_user
    chat_id = update.effective_chat.id
    register_message(user.id, chat_id, update.message.message_id)
    await finish_process(context.bot, user.id, show_menu=True, menu_text="✅ Готово!")


async def cmd_new(update, context):
    user = update.effective_user
    chat_id = update.effective_chat.id
    msg = await update.message.reply_text("🧹 Используй /start для чистого старта")
    register_message(user.id, chat_id, update.message.message_id)
    register_message(user.id, chat_id, msg.message_id)
    await asyncio.sleep(3)
    await finish_process(context.bot, user.id, show_menu=True)


async def cmd_rub(update, context):
    user = update.effective_user
    chat_id = update.effective_chat.id
    msg = await update.message.reply_text("💱 Получаю актуальный курс рубля...")
    register_message(user.id, chat_id, update.message.message_id)
    register_message(user.id, chat_id, msg.message_id)
    try:
        summa = db_get_summa(user.id)
        result = await asyncio.wait_for(
            asyncio.to_thread(_fetch_rub_direct, summa), timeout=15.0
        )
        await msg.edit_text(result, parse_mode="Markdown")
    except asyncio.TimeoutError:
        await msg.edit_text("⏰ Сайт не ответил вовремя.")
    except Exception as e:
        logger.error(f"Rub error: {e}")
        await msg.edit_text("⚠️ Не удалось получить курс рубля.")
    asyncio.create_task(_auto_cleanup(context.bot, user.id, chat_id, msg.message_id, delay=30))


async def cmd_timer(update, context):
    user = update.effective_user
    chat_id = update.effective_chat.id

    if not context.args:
        msg = await update.message.reply_text("❌ Укажи время. Пример: /t 300 или /t 5m")
        register_message(user.id, chat_id, update.message.message_id)
        register_message(user.id, chat_id, msg.message_id)
        asyncio.create_task(_auto_cleanup(context.bot, user.id, chat_id, msg.message_id, delay=5))
        return

    seconds = parse_duration_seconds(context.args[0])
    if seconds is None:
        msg = await update.message.reply_text("❌ Укажи время. Пример: /t 300, /t 5m или /t 1h30m")
        register_message(user.id, chat_id, update.message.message_id)
        register_message(user.id, chat_id, msg.message_id)
        asyncio.create_task(_auto_cleanup(context.bot, user.id, chat_id, msg.message_id, delay=5))
        return

    if seconds <= 0 or seconds > 86400:
        msg = await update.message.reply_text("❌ От 1 до 86400 секунд.")
        register_message(user.id, chat_id, update.message.message_id)
        register_message(user.id, chat_id, msg.message_id)
        asyncio.create_task(_auto_cleanup(context.bot, user.id, chat_id, msg.message_id, delay=5))
        return

    timer_text = " ".join(context.args[1:]) if len(context.args) > 1 else "Таймер завершён!"
    fire_at = datetime.now() + timedelta(seconds=seconds)
    rid = next_reminder_id(chat_id)
    _schedule_reminder(context.job_queue, chat_id, rid, timer_text, fire_at, True, "none")
    await asyncio.to_thread(db_save_reminder, chat_id, rid, timer_text, fire_at, True)

    mins, secs = divmod(seconds, 60)
    duration = f"{mins}м {secs}с" if mins else f"{secs}с"
    msg = await update.message.reply_text(f"⏱ Таймер запущен на {duration}")
    register_message(user.id, chat_id, update.message.message_id)
    register_message(user.id, chat_id, msg.message_id)
    asyncio.create_task(_auto_cleanup(context.bot, user.id, chat_id, update.message.message_id, delay=3))
    asyncio.create_task(_auto_cleanup(context.bot, user.id, chat_id, msg.message_id, delay=5))


async def shortcut_handler(update, context):
    user = update.effective_user
    chat_id = update.effective_chat.id
    cmd = update.message.text.strip().lstrip("/").split()[0]
    query = SHORTCUTS.get(cmd)
    register_message(user.id, chat_id, update.message.message_id)
    if query:
        await do_search(update, query, user.id, chat_id, context.bot)
    else:
        msg = await update.message.reply_text("❌ Неизвестная команда")
        register_message(user.id, chat_id, msg.message_id)
        asyncio.create_task(_auto_cleanup(context.bot, user.id, chat_id, msg.message_id, delay=3))


# ─── Utilities ────────────────────────────────────────────────────────────────

async def _auto_cleanup(bot, user_id: int, chat_id: int, message_id: int, delay: int = 5):
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass


def _format_reminder_time(r: dict) -> str:
    if r.get("delivered"):
        return "сработало"
    t = r["time"]
    now = datetime.now()
    if t.date() == now.date():
        return t.strftime("%H:%M")
    elif t.date() == (now + timedelta(days=1)).date():
        return f"завтра {t.strftime('%H:%M')}"
    else:
        return t.strftime("%d.%m %H:%M")


def md(text) -> str:
    from telegram.helpers import escape_markdown
    return escape_markdown(str(text), version=1)


from datetime import datetime, timedelta