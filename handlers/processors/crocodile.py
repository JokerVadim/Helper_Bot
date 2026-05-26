"""Crocodile game — угадай слово по описанию."""
import logging
import os
import random
from datetime import datetime, timedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from handlers.processors import register_callback_handler
from handlers.processors.games import register_game_direct, show_games_menu
from utils import _pad, md
from keyboards import btn_menu

logger = logging.getLogger(__name__)

# Register this game in the games hub
register_game_direct("crocodile", "🎭 Крокодил")

# ─── Words file ──────────────────────────────────────────────────────────────
WORDS_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "games", "crocodile_words.txt")

CATEGORIES: dict[str, list[str]] = {}
_WORDS_LOADED = False


def _load_words():
    global CATEGORIES, _WORDS_LOADED
    if _WORDS_LOADED:
        return
    CATEGORIES.clear()
    current_cat = None
    try:
        with open(WORDS_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                if line.startswith("#"):
                    current_cat = line[1:].strip()
                    CATEGORIES[current_cat] = []
                elif current_cat:
                    CATEGORIES[current_cat].append(line)
    except OSError:
        logger.warning("Words file not found at %s", WORDS_FILE)
    _WORDS_LOADED = True


# ─── Game sessions ───────────────────────────────────────────────────────────
sessions: dict[int, dict] = {}


async def _build_game_text(session: dict) -> str:
    word = session["words"][session["index"]]
    word_display = f"*{md(word)}*" if session["shown"] else "❓❓❓"
    timer_line = ""
    if session.get("timer_end"):
        remaining = int((session["timer_end"] - datetime.now()).total_seconds())
        if remaining > 0:
            timer_line = f"\n⏱ Осталось: *{remaining // 60}:{remaining % 60:02d}*"
        else:
            timer_line = "\n⏰ *Время вышло!*"
    return _pad(
        f"🎭 *Крокодил*\n"
        f"Категория: *{md(session['category'])}*\n\n"
        f"{word_display}"
        f"\n\n✅ Угадано: *{session['guessed']}*   🔄 Пропущено: *{session['skipped']}*"
        f"{timer_line}"
    )


def _build_game_keyboard(session: dict) -> list:
    total = len(session["words"])
    is_last = session["index"] >= total - 1
    finish_lbl = "🏁 Закончить" if not is_last else "🏁 Итог"

    if session["shown"]:
        row1 = [
            InlineKeyboardButton("🙈 Скрыть", callback_data="croc_hide"),
            InlineKeyboardButton("✅ Угадал", callback_data="croc_guess"),
            InlineKeyboardButton("🔄 Пропустить", callback_data="croc_skip"),
        ]
    else:
        row1 = [
            InlineKeyboardButton("👀 Показать", callback_data="croc_show"),
            InlineKeyboardButton("🔄 Пропустить", callback_data="croc_skip"),
        ]

    timer_running = session.get("timer_job_name") is not None
    if timer_running:
        row2 = [InlineKeyboardButton("⏱ ⏸ Стоп", callback_data="croc_stop_timer")]
    else:
        row2 = [
            InlineKeyboardButton("⏱ 60с", callback_data="croc_timer_60"),
            InlineKeyboardButton("⏱ 120с", callback_data="croc_timer_120"),
        ]
    row2.append(InlineKeyboardButton(finish_lbl, callback_data="croc_end"))

    row3 = [
        InlineKeyboardButton("◀️ К играм", callback_data="back_to_games"),
        btn_menu(),
    ]

    return [row1, row2, row3]


# ─── Category picker ─────────────────────────────────────────────────────────

async def show_categories(query):
    _load_words()
    keyboard = [
        [InlineKeyboardButton(cat, callback_data=f"croc_start_{i}")]
        for i, cat in enumerate(sorted(CATEGORIES.keys()))
    ]
    keyboard.append([InlineKeyboardButton("◀️ К играм", callback_data="back_to_games"), btn_menu()])
    text = _pad("🎭 *Крокодил*\n\nВыбери категорию:")
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))


async def start_game(query, category: str, context):
    user = query.from_user
    words = list(CATEGORIES[category])
    if not words:
        await query.answer("Категория пуста")
        return
    random.shuffle(words)
    session = {
        "category": category,
        "words": words,
        "index": 0,
        "guessed": 0,
        "skipped": 0,
        "shown": False,
        "timer_end": None,
        "timer_job_name": None,
    }
    sessions[user.id] = session

    text = await _build_game_text(session)
    keyboard = _build_game_keyboard(session)
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))


async def _next_word(query, session: dict, context):
    session["index"] += 1
    session["shown"] = False
    session["timer_end"] = None
    await _cancel_timer_by_name(query.from_user.id, context)

    if session["index"] >= len(session["words"]):
        await _show_results(query, session)
        return

    text = await _build_game_text(session)
    keyboard = _build_game_keyboard(session)
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))


async def _show_results(query, session: dict):
    user = query.from_user
    total = len(session["words"])
    cat_index = _get_category_index(session["category"])
    text = _pad(
        f"🏁 *Игра окончена!*\n\n"
        f"🎭 Категория: *{md(session['category'])}*\n"
        f"✅ Угадано: *{session['guessed']}*\n"
        f"🔄 Пропущено: *{session['skipped']}*\n"
        f"📊 Всего слов: *{total}*"
    )
    keyboard = [
        [InlineKeyboardButton("🔄 Ещё раз", callback_data=f"croc_restart_{cat_index}")],
        [InlineKeyboardButton("◀️ К категориям", callback_data="croc_categories"),
         btn_menu()],
    ]
    sessions.pop(user.id, None)
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))


# ─── Timer ───────────────────────────────────────────────────────────────────

async def _cancel_timer_by_name(user_id: int, context):
    if context.job_queue is None:
        return
    session = sessions.get(user_id)
    if not session:
        return
    job_name = session.get("timer_job_name")
    if job_name:
        try:
            for j in context.job_queue.get_jobs_by_name(job_name):
                j.schedule_removal()
        except Exception:
            logger.warning("Failed to cancel timer for user %d", user_id)
        session["timer_job_name"] = None
        session["timer_end"] = None


async def _timer_tick(context):
    job = context.job
    user_id = job.data["user_id"]
    session = sessions.get(user_id)
    if not session:
        return
    # Если таймер уже сброшен — ничего не делаем
    job_name = job.name
    if session.get("timer_job_name") != job_name:
        return
    now = datetime.now()
    if session.get("timer_end") and now >= session["timer_end"]:
        session["timer_job_name"] = None
        session["timer_end"] = None
        session["shown"] = True
        try:
            bot = context.bot
            chat_id = job.data.get("chat_id")
            message_id = job.data.get("message_id")
            text = await _build_game_text(session)
            keyboard = _build_game_keyboard(session)
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            session["shown"] = False
            session["skipped"] += 1
            session["index"] += 1
            if session["index"] >= len(session["words"]):
                total = len(session["words"])
                cat_index = _get_category_index(session["category"])
                result_text = _pad(
                    f"🏁 *Игра окончена!*\n\n"
                    f"🎭 Категория: *{md(session['category'])}*\n"
                    f"✅ Угадано: *{session['guessed']}*\n"
                    f"🔄 Пропущено: *{session['skipped']}*\n"
                    f"📊 Всего слов: *{total}*"
                )
                result_keyboard = [
                    [InlineKeyboardButton("🔄 Ещё раз", callback_data=f"croc_restart_{cat_index}")],
                    [InlineKeyboardButton("◀️ К категориям", callback_data="croc_categories"),
                     btn_menu()],
                ]
                sessions.pop(user_id, None)
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=result_text,
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(result_keyboard),
                )
            else:
                text2 = await _build_game_text(session)
                keyboard2 = _build_game_keyboard(session)
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text2,
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(keyboard2),
                )
        except Exception as e:
            logger.error("Timer tick error: %s", e)
        return

    try:
        bot = job.data.get("bot")
        chat_id = job.data.get("chat_id")
        msg_id = job.data.get("message_id")
        if bot and chat_id and msg_id:
            text = await _build_game_text(session)
            keyboard = _build_game_keyboard(session)
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=msg_id,
                text=text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
    except Exception as e:
        logger.debug("Timer tick edit failed: %s", e)


async def _skip_timeout(query, session, context):
    text = await _build_game_text(session)
    keyboard = _build_game_keyboard(session)
    try:
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception:
        pass
    # auto skip after timeout
    await query.answer("⏰ Время вышло!")
    session["shown"] = False
    session["skipped"] += 1
    await _next_word(query, session, context)


# ─── Callback handlers ──────────────────────────────────────────────────────

@register_callback_handler("game_crocodile")
async def callback_open_crocodile(query, context, data, user, chat_id, bot):
    await query.answer()
    await show_categories(query)


def _get_category_index(category: str) -> int:
    sorted_cats = sorted(CATEGORIES.keys())
    try:
        return sorted_cats.index(category)
    except ValueError:
        return 0


@register_callback_handler("croc_categories")
async def callback_croc_categories(query, context, data, user, chat_id, bot):
    await query.answer()
    await _cancel_timer_by_name(user.id, context)
    sessions.pop(user.id, None)
    await show_categories(query)


@register_callback_handler("croc_start_")
async def callback_croc_start(query, context, data, user, chat_id, bot):
    try:
        cat_idx = int(data.split("_")[-1])
    except (ValueError, IndexError):
        await show_categories(query)
        return
    _load_words()
    categories = sorted(CATEGORIES.keys())
    if cat_idx < 0 or cat_idx >= len(categories):
        await show_categories(query)
        return
    await start_game(query, categories[cat_idx], context)


@register_callback_handler("croc_show")
async def callback_croc_show(query, context, data, user, chat_id, bot):
    await query.answer()
    session = sessions.get(user.id)
    if not session:
        return
    session["shown"] = True
    text = await _build_game_text(session)
    keyboard = _build_game_keyboard(session)
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))


@register_callback_handler("croc_hide")
async def callback_croc_hide(query, context, data, user, chat_id, bot):
    await query.answer()
    session = sessions.get(user.id)
    if not session:
        return
    session["shown"] = False
    text = await _build_game_text(session)
    keyboard = _build_game_keyboard(session)
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))


@register_callback_handler("croc_guess")
async def callback_croc_guess(query, context, data, user, chat_id, bot):
    session = sessions.get(user.id)
    if not session:
        return
    await query.answer("✅ Угадали!", show_alert=True)
    session["guessed"] += 1
    await _cancel_timer_by_name(user.id, context)
    await _next_word(query, session, context)


@register_callback_handler("croc_skip")
async def callback_croc_skip(query, context, data, user, chat_id, bot):
    await query.answer("🔄 Пропущено")
    session = sessions.get(user.id)
    if not session:
        return
    session["skipped"] += 1
    await _cancel_timer_by_name(user.id, context)
    await _next_word(query, session, context)


@register_callback_handler("croc_timer_")
async def callback_croc_timer(query, context, data, user, chat_id, bot):
    await query.answer()
    session = sessions.get(user.id)
    if not session:
        return
    if context.job_queue is None:
        return
    await _cancel_timer_by_name(user.id, context)
    try:
        seconds = int(data.split("_")[-1])
    except (ValueError, IndexError):
        await query.answer("Ошибка в данных таймера")
        return
    session["timer_end"] = datetime.now() + timedelta(seconds=seconds)
    job_name = f"croc_timer_{user.id}"
    session["timer_job_name"] = job_name

    context.job_queue.run_repeating(
        _timer_tick,
        interval=5,
        first=1,
        name=job_name,
        data={
            "user_id": user.id,
            "bot": bot,
            "chat_id": chat_id,
            "message_id": query.message.message_id,
        },
    )

    text = await _build_game_text(session)
    keyboard = _build_game_keyboard(session)
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))


@register_callback_handler("croc_stop_timer")
async def callback_croc_stop_timer(query, context, data, user, chat_id, bot):
    await query.answer()
    session = sessions.get(user.id)
    if not session:
        return
    await _cancel_timer_by_name(user.id, context)
    text = await _build_game_text(session)
    keyboard = _build_game_keyboard(session)
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))


@register_callback_handler("croc_end")
async def callback_croc_end(query, context, data, user, chat_id, bot):
    await query.answer()
    session = sessions.get(user.id)
    if not session:
        return
    await _cancel_timer_by_name(user.id, context)
    await _show_results(query, session)


@register_callback_handler("croc_restart_")
async def callback_croc_restart(query, context, data, user, chat_id, bot):
    await query.answer()
    await _cancel_timer_by_name(user.id, context)
    sessions.pop(user.id, None)
    try:
        cat_idx = int(data.split("_")[-1])
    except (ValueError, IndexError):
        await show_categories(query)
        return
    _load_words()
    categories = sorted(CATEGORIES.keys())
    if 0 <= cat_idx < len(categories):
        await start_game(query, categories[cat_idx], context)
    else:
        await show_categories(query)


@register_callback_handler("back_to_games")
async def callback_back_to_games(query, context, data, user, chat_id, bot):
    await query.answer()
    sessions.pop(user.id, None)
    await show_games_menu(query)
