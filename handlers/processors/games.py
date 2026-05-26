"""Games menu hub. Регистрирует callback open_games и управляет списком игр."""
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from handlers.processors import register_callback_handler
from utils import _pad
from keyboards import btn_menu

logger = logging.getLogger(__name__)

GAMES: dict[str, dict] = {}


def register_game(game_id: str, name: str):
    """Зарегистрировать игру. Можно использовать как декоратор или напрямую."""
    def decorator(func):
        GAMES[game_id] = {"name": name, "handler": func}
        return func
    return decorator


def register_game_direct(game_id: str, name: str):
    """Зарегистрировать игру без функции-обработчика (колбэк обрабатывается отдельно)."""
    GAMES[game_id] = {"name": name, "handler": None}


async def show_games_menu(query):
    """Показать меню игр."""
    keyboard = [
        [InlineKeyboardButton(info["name"], callback_data=f"game_{gid}")]
        for gid, info in GAMES.items()
    ]
    keyboard.append([btn_menu()])
    text = _pad("🎮 *Игры*\n\nВыбери игру:")
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))


@register_callback_handler("open_games")
async def callback_open_games(query, context, data, user, chat_id, bot):
    await query.answer()
    await show_games_menu(query)
