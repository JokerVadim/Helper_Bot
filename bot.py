"""
Telegram Assistant Bot
Process Manager + SQLite + история диалога Groq
"""
import asyncio
import logging
import os

from telegram import BotCommand, Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

from dotenv import load_dotenv
load_dotenv()

from db import init_db, db_get_pending_reminders, db_save_reminder, db_update_reminder, db_delete_reminder
from ai import init_ai, groq_client, tavily
from handlers.session import reminders, reminder_counter, _store_memory_reminder
from handlers.reminders import _schedule_reminder, _row_to_reminder, reminder_callback
from handlers.commands import (
    cmd_start, cmd_cancel, cmd_status, cmd_addlist, cmd_showlists,
    cmd_done, cmd_new, cmd_rub, cmd_timer, shortcut_handler,
)
from handlers.callbacks import button_handler
from keyboards import show_main_menu
from shortcuts import SHORTCUTS
from config import MAX_SEARCH_RESULTS

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)


def md(text) -> str:
    from telegram.helpers import escape_markdown
    return escape_markdown(str(text), version=1)


async def set_commands(app: Application):
    commands = [
        BotCommand("start", "Запустить бота и очистить чат"),
        BotCommand("help",  "Помощь"),
        BotCommand("rub",   "Курс рубля"),
        BotCommand("t",     "Таймер (секунды)"),
        BotCommand("al",    "Создать список"),
        BotCommand("sls",   "Мои списки"),
        BotCommand("status", "Статус бота"),
        BotCommand("cancel", "Отменить текущее действие"),
        BotCommand("done",  "Завершить текущий процесс"),
    ]
    await app.bot.delete_my_commands()
    await app.bot.set_my_commands(commands)


async def restore_reminders(app: Application):
    from datetime import datetime
    from utils.time_utils import next_repeat_time

    rows = await asyncio.to_thread(db_get_pending_reminders)
    restored = 0
    missed = 0
    for row in rows:
        chat_id  = row["chat_id"]
        rid      = row["rid"]
        text     = row["text"]
        fire_at  = datetime.strptime(row["fire_at"], "%Y-%m-%d %H:%M:%S")
        is_timer = bool(row["is_timer"])
        repeat_type = row.get("repeat_type") or "none"
        delivered = bool(row.get("delivered", 0))
        delay    = (fire_at - datetime.now()).total_seconds()

        if delivered:
            _store_memory_reminder(chat_id, _row_to_reminder(row))
            reminder_counter[chat_id] = max(reminder_counter.get(chat_id, 0), rid)
            continue

        if delay <= 0:
            missed += 1
            try:
                title = "⏱ Пропущенный таймер" if is_timer else "⏰ Пропущенное напоминание"
                await app.bot.send_message(
                    chat_id=chat_id,
                    text=f"{title}\n\n{md(text)}\n\n_Было запланировано: {fire_at.strftime('%d.%m %H:%M')}_",
                    parse_mode="Markdown",
                    reply_markup=None if is_timer else InlineKeyboardMarkup([
                        [
                            InlineKeyboardButton("+10м", callback_data=f"snooze_{rid}_10m"),
                            InlineKeyboardButton("+1ч", callback_data=f"snooze_{rid}_1h"),
                            InlineKeyboardButton("Завтра", callback_data=f"snooze_{rid}_1d"),
                        ],
                        [InlineKeyboardButton("Открыть", callback_data=f"viewrem_{rid}")],
                    ])
                )
            except Exception as e:
                logger.error(f"Missed reminder send error: {e}")

            if is_timer:
                await asyncio.to_thread(db_delete_reminder, chat_id, rid)
                continue

            if repeat_type != "none":
                next_time = next_repeat_time(fire_at, repeat_type)
                if next_time:
                    await asyncio.to_thread(db_update_reminder, chat_id, rid, fire_at=next_time, delivered=False)
                    _schedule_reminder(app.job_queue, chat_id, rid, text, next_time, False, repeat_type)
                    restored += 1
                continue

            await asyncio.to_thread(db_update_reminder, chat_id, rid, delivered=True)
            row["delivered"] = 1
            _store_memory_reminder(chat_id, _row_to_reminder(row))
            reminder_counter[chat_id] = max(reminder_counter.get(chat_id, 0), rid)
            continue

        _schedule_reminder(app.job_queue, chat_id, rid, text, fire_at, is_timer, repeat_type)
        restored += 1
    logger.info(f"🔁 Восстановлено напоминаний: {restored}, пропущенных: {missed}")


async def handle_message(update: Update, context):
    from telegram import InlineKeyboardMarkup
    from handlers.session import processes, register_message
    from handlers.reminders import next_reminder_id, _schedule_reminder
    from keyboards import btn_menu, btn_cancel
    from utils.time_utils import (
        parse_reminder_time_arg, parse_time_arg, parse_clock,
        next_daily_at, next_monthly_at, next_yearly_at, describe_when,
        _repeat_icon, _repeat_label,
    )
    from ai import do_search, _ask_groq_with_history, history_add
    from db import db_add_item
    from shortcuts import SHORTCUTS
    import uuid
    from datetime import datetime, timedelta

    message = update.message or update.effective_message
    if not message:
        return

    user    = update.effective_user
    chat_id = update.effective_chat.id
    text    = message.text.strip()

    if not text or text.startswith("/"):
        return

    register_message(user.id, chat_id, message.message_id)

    # ── Нет процесса — диалог с Groq ──
    if user.id not in processes:
        asyncio.create_task(_auto_cleanup(context.bot, user.id, chat_id, message.message_id, delay=1))

        if "найди" in text.lower():
            await do_search(update, text, user.id, chat_id, context.bot)
            await show_main_menu(context.bot, user.id, "🔍 Что дальше?")
        else:
            answer = await asyncio.to_thread(_ask_groq_with_history, user.id, text)
            history_add(user.id, "user", text)
            history_add(user.id, "assistant", answer)
            try:
                await message.reply_text(answer, parse_mode="Markdown")
            except Exception:
                await message.reply_text(answer)
        return

    proc      = processes[user.id]
    proc_type = proc["type"]
    state     = proc["state"]

    # ────────── СОЗДАНИЕ СПИСКА ──────────
    if proc_type == "list":
        step = state.get("step")

        if step == "creating_list_name":
            list_id = str(uuid.uuid4())[:8]
            await asyncio.to_thread(db_create_list, list_id, "personal", text, user.id)
            state["step"]      = "adding_items"
            state["list_id"]   = list_id
            state["list_name"] = text

            reply = await message.reply_text(
                f"✅ Список *{md(text)}* создан!\n\nОтправляй элементы по одному.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Завершить ввод", callback_data=f"done_adding_{list_id}")],
                    [btn_cancel()],
                ])
            )
            register_message(user.id, chat_id, reply.message_id)

        elif step == "adding_items":
            list_id   = state.get("list_id")
            list_name = state.get("list_name", "список")
            await asyncio.to_thread(db_add_item, list_id, user.id, text)

            prev_confirm = state.get("last_confirm_id")
            if prev_confirm:
                try:
                    await context.bot.delete_message(chat_id=chat_id, message_id=prev_confirm)
                except Exception:
                    pass
                if prev_confirm in proc.get("messages", []):
                    proc["messages"].remove(prev_confirm)

            reply = await message.reply_text(
                f"✅ *{md(text)}* добавлен в *{md(list_name)}*",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Завершить ввод", callback_data=f"done_adding_{list_id}")],
                    [btn_cancel()],
                ])
            )
            register_message(user.id, chat_id, reply.message_id)
            state["last_confirm_id"] = reply.message_id

    # ────────── НАПОМИНАНИЕ ──────────
    elif proc_type == "reminder":
        step = state.get("step")

        if step == "waiting_repeat":
            reply = await message.reply_text(
                "Выбери тип напоминания кнопкой ниже.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔔 Одноразовое", callback_data="remtype_none")],
                    [InlineKeyboardButton("🔁 Ежедневное", callback_data="remtype_daily")],
                    [InlineKeyboardButton("📅 Ежемесячное", callback_data="remtype_monthly")],
                    [InlineKeyboardButton("🎂 Ежегодное", callback_data="remtype_yearly")],
                    [btn_cancel()],
                ])
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
            import re
            m = re.fullmatch(r'\s*(\d{1,2})\.(\d{1,2})\s*', text)
            if not m:
                reply = await message.reply_text(
                    "❌ Введи дату в формате *дд.мм*, например *12.08*:",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
                )
                register_message(user.id, chat_id, reply.message_id)
                return
            day, month = int(m.group(1)), int(m.group(2))
            import calendar
            if month < 1 or month > 12 or day < 1 or day > calendar.monthrange(2024, month)[1]:
                reply = await message.reply_text(
                    "❌ Такой даты нет. Введи дату в формате *дд.мм*:",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
                )
                register_message(user.id, chat_id, reply.message_id)
                return
            state["year_day"] = day
            state["year_month"] = month
            state["step"] = "waiting_repeat_clock"
            reply = await message.reply_text(
                f"🎂 Каждый год {day:02d}.{month:02d}.\n\nТеперь введи время:\n\n• *09:00*",
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
                asyncio.create_task(_auto_cleanup(context.bot, user.id, chat_id, reply.message_id, delay=8))
                return

            state["fire_at"] = fire_at
            state["step"]    = "waiting_text"

            reply = await message.reply_text(
                f"⏰ Время: *{describe_when(fire_at)}*\n\nЧто напомнить?",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
            )
            register_message(user.id, chat_id, reply.message_id)

        elif step == "waiting_text":
            from handlers.reminders import next_reminder_id, _schedule_reminder
            fire_at = state["fire_at"]
            repeat_type = state.get("repeat_type", "none")
            rid = next_reminder_id(chat_id)
            _schedule_reminder(context.job_queue, chat_id, rid, text, fire_at, False, repeat_type)
            await asyncio.to_thread(db_save_reminder, chat_id, rid, text, fire_at, False, repeat_type)

            from handlers.session import finish_process
            await finish_process(context.bot, user.id, show_menu=False)
            await show_main_menu(context.bot, user.id, f"✅ {_repeat_icon(repeat_type)} Напоминание на *{describe_when(fire_at)}* создано!")

    # ────────── ТАЙМЕР ──────────
    elif proc_type == "timer":
        step = state.get("step")

        if step == "waiting_time":
            fire_at = parse_time_arg(text)
            if not fire_at:
                reply = await message.reply_text(
                    "❌ Неверный формат. Введи:\n• *60* — секунды\n• *5m* — минуты\n• *1h30m*",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
                )
                register_message(user.id, chat_id, reply.message_id)
                asyncio.create_task(_auto_cleanup(context.bot, user.id, chat_id, reply.message_id, delay=5))
                return

            seconds = int((fire_at - datetime.now()).total_seconds())
            state["seconds"] = seconds
            state["step"]    = "waiting_text"

            reply = await message.reply_text(
                "📝 Подпись таймера (или `-` чтобы пропустить):",
                reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
            )
            register_message(user.id, chat_id, reply.message_id)

        elif step == "waiting_text":
            from handlers.reminders import next_reminder_id, _schedule_reminder
            seconds    = state["seconds"]
            timer_text = text if text != "-" else "Таймер завершён!"
            fire_at    = datetime.now() + timedelta(seconds=seconds)
            rid = next_reminder_id(chat_id)
            _schedule_reminder(context.job_queue, chat_id, rid, timer_text, fire_at, True, "none")
            await asyncio.to_thread(db_save_reminder, chat_id, rid, timer_text, fire_at, True)

            mins, secs = divmod(seconds, 60)
            duration = f"{mins}м {secs}с" if mins else f"{secs}с"
            from handlers.session import finish_process
            await finish_process(context.bot, user.id, show_menu=False)
            await show_main_menu(context.bot, user.id, f"✅ Таймер на *{duration}* запущен!")

    # ────────── СУММА ──────────
    elif proc_type == "summa":
        if state.get("step") == "waiting_summa":
            clean = text.replace(" ", "").replace(",", "").replace(".", "")
            if not clean.isdigit():
                reply = await message.reply_text(
                    "❌ Введи число (например: 500000):",
                    reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
                )
                register_message(user.id, chat_id, reply.message_id)
                asyncio.create_task(_auto_cleanup(context.bot, user.id, chat_id, reply.message_id, delay=5))
                return

            from db import db_set_summa
            summa_val = float(clean)
            db_set_summa(user.id, summa_val)
            formatted = f"{int(summa_val):,}".replace(",", " ")
            from handlers.session import finish_process
            await finish_process(context.bot, user.id, show_menu=False)
            await show_main_menu(context.bot, user.id, f"✅ Сумма сохранена: *{formatted}* сум")

    # ────────── ПОИСК ──────────
    elif proc_type == "search":
        if state.get("step") == "waiting_query":
            asyncio.create_task(_auto_cleanup(context.bot, user.id, chat_id, message.message_id, delay=1))
            from handlers.session import finish_process
            await finish_process(context.bot, user.id, show_menu=False)
            from ai import do_search
            await do_search(update, text, user.id, chat_id, context.bot)
            await show_main_menu(context.bot, user.id, "🔍 Что дальше?")

    # ────────── РЕДАКТИРОВАНИЕ НАПОМИНАНИЯ ──────────
    elif proc_type == "edit_reminder":
        from handlers.reminders import (
            next_reminder_id, _schedule_reminder, _cancel_reminder_job,
            _find_memory_reminder, _row_to_reminder,
        )
        from handlers.session import finish_process

        rid = state.get("rid")
        item = _find_memory_reminder(chat_id, rid)
        if not item:
            row = await asyncio.to_thread(db_get_reminder, chat_id, rid)
            item = _row_to_reminder(row) if row else None
        if not item:
            await finish_process(context.bot, user.id, show_menu=True, menu_text="❌ Напоминание не найдено.")
            return

        if state.get("step") == "waiting_text":
            item["text"] = text
            await asyncio.to_thread(db_update_reminder, chat_id, rid, text=text)
            if item.get("job"):
                _cancel_reminder_job(chat_id, rid)
                _schedule_reminder(
                    context.job_queue, chat_id, rid, text, item["time"],
                    item.get("is_timer", False), item.get("repeat_type", "none")
                )
            await finish_process(context.bot, user.id, show_menu=True, menu_text="✅ Текст напоминания обновлён.")
            return

        if state.get("step") == "waiting_month_day":
            import calendar
            clean = text.strip()
            if not clean.isdigit() or not (1 <= int(clean) <= 31):
                reply = await message.reply_text("❌ Введи число месяца от 1 до 31:", reply_markup=InlineKeyboardMarkup([[btn_cancel()]]))
                register_message(user.id, chat_id, reply.message_id)
                return
            state["month_day"] = int(clean)
            state["step"] = "waiting_repeat_clock"
            reply = await message.reply_text("Теперь введи время в формате *чч:мм*:", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[btn_cancel()]]))
            register_message(user.id, chat_id, reply.message_id)
            return

        if state.get("step") == "waiting_year_date":
            import re, calendar
            m = re.fullmatch(r'\s*(\d{1,2})\.(\d{1,2})\s*', text)
            if not m:
                reply = await message.reply_text("❌ Введи дату в формате *дд.мм*:", reply_markup=InlineKeyboardMarkup([[btn_cancel()]]))
                register_message(user.id, chat_id, reply.message_id)
                return
            day, month = int(m.group(1)), int(m.group(2))
            if month < 1 or month > 12 or day < 1 or day > calendar.monthrange(2024, month)[1]:
                reply = await message.reply_text("❌ Такой даты нет. Введи дату в формате *дд.мм*:", reply_markup=InlineKeyboardMarkup([[btn_cancel()]]))
                register_message(user.id, chat_id, reply.message_id)
                return
            state["year_day"] = day
            state["year_month"] = month
            state["step"] = "waiting_repeat_clock"
            reply = await message.reply_text("Теперь введи время в формате *чч:мм*:", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[btn_cancel()]]))
            register_message(user.id, chat_id, reply.message_id)
            return

        if state.get("step") == "waiting_repeat_clock":
            clock = parse_clock(text)
            if not clock:
                reply = await message.reply_text("❌ Введи время в формате *чч:мм*:", reply_markup=InlineKeyboardMarkup([[btn_cancel()]]))
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
            _schedule_reminder(
                context.job_queue, chat_id, rid, item["text"], fire_at,
                item.get("is_timer", False), repeat_type
            )
            await asyncio.to_thread(db_update_reminder, chat_id, rid, fire_at=fire_at, delivered=False)
            await finish_process(context.bot, user.id, show_menu=True, menu_text="✅ Время напоминания обновлено.")
            return

        if state.get("step") == "waiting_time":
            repeat_type = state.get("repeat_type", item.get("repeat_type", "none"))
            fire_at = parse_reminder_time_arg(text, repeat_type)
            if not fire_at:
                reply = await message.reply_text("❌ Не понял время. Попробуй ещё раз:", reply_markup=InlineKeyboardMarkup([[btn_cancel()]]))
                register_message(user.id, chat_id, reply.message_id)
                return
            _cancel_reminder_job(chat_id, rid)
            item["time"] = fire_at
            item["delivered"] = False
            _schedule_reminder(
                context.job_queue, chat_id, rid, item["text"], fire_at,
                item.get("is_timer", False), repeat_type
            )
            await asyncio.to_thread(db_update_reminder, chat_id, rid, fire_at=fire_at, delivered=False)
            await finish_process(context.bot, user.id, show_menu=True, menu_text="✅ Время напоминания обновлено.")


# ─── Auto cleanup helper ───────────────────────────────────────────────────────

async def _auto_cleanup(bot, user_id: int, chat_id: int, message_id: int, delay: int = 5):
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass


# ─── Entry point ─────────────────────────────────────────────────────────────

BOT_TOKEN  = os.getenv("BOT_TOKEN")
TAVILY_KEY = os.getenv("TAVILY_KEY")
GROQ_KEY   = os.getenv("GROQ_KEY")

missing_env = [name for name, value in {
    "BOT_TOKEN": BOT_TOKEN,
    "TAVILY_KEY": TAVILY_KEY,
    "GROQ_KEY": GROQ_KEY,
}.items() if not value]
if missing_env:
    raise RuntimeError(f"Missing required environment variables: {', '.join(missing_env)}")

init_ai(GROQ_KEY, TAVILY_KEY)

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from db import db_get_reminder, db_create_list


if __name__ == "__main__":
    init_db()

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(set_commands)
        .connect_timeout(60)
        .read_timeout(60)
        .write_timeout(60)
        .pool_timeout(60)
        .build()
    )

    app.job_queue.run_once(lambda ctx: asyncio.ensure_future(restore_reminders(app)), when=2)

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help",  cmd_start))
    app.add_handler(CommandHandler("rub",   cmd_rub))
    app.add_handler(CommandHandler("new",   cmd_new))
    app.add_handler(CommandHandler("done",  cmd_done))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("t",     cmd_timer))
    app.add_handler(CommandHandler("timer", cmd_timer))
    app.add_handler(CommandHandler("al",    cmd_addlist))
    app.add_handler(CommandHandler("sls",   cmd_showlists))
    app.add_handler(CallbackQueryHandler(button_handler))

    for _cmd in SHORTCUTS:
        app.add_handler(CommandHandler(_cmd, shortcut_handler))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🚀 Бот запущен с Process Manager + SQLite + Groq History")
    app.run_polling()
