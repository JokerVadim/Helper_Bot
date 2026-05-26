"""Domain processors package.

Каждый модуль в этой папке отвечает за один домен (списки, напоминания, карты и т.д.)
и предоставляет:
- message_handler(update, context, proc, state) — для обработки сообщений пользователя
- callback_handlers — список (pattern, handler) для button_handler
"""

from typing import Callable, Awaitable

# Типы для диспетчеров
MessageHandler = Callable[..., Awaitable[None]]
CallbackHandler = Callable[..., Awaitable[None]]

# Регистры обработчиков
MESSAGE_HANDLERS: dict[str, MessageHandler] = {}
CALLBACK_PATTERNS: list[tuple[str, CallbackHandler]] = []


def register_message_handler(proc_type: str):
    """Декоратор для регистрации обработчика сообщений для типа процесса."""
    def decorator(func: MessageHandler):
        MESSAGE_HANDLERS[proc_type] = func
        return func
    return decorator


def register_callback_handler(pattern: str):
    """Декоратор для регистрации обработчика callback по префиксу data."""
    def decorator(func: CallbackHandler):
        CALLBACK_PATTERNS.append((pattern, func))
        return func
    return decorator


def get_message_handler(proc_type: str) -> MessageHandler | None:
    return MESSAGE_HANDLERS.get(proc_type)


def get_callback_handler(data: str) -> tuple[CallbackHandler | None, str | None]:
    """Найти первый подходящий обработчик.

    - Если паттерн оканчивается на "_", используется match по префиксу (data.startswith)
      для поддержки параметризованных колбэков (например: viewweather_123).
    - Иначе — только точное совпадение (data == pattern).
    """
    for pattern, handler in CALLBACK_PATTERNS:
        if data == pattern:
            return handler, pattern
        if pattern.endswith("_") and data.startswith(pattern):
            return handler, pattern
    return None, None


# Импортируем модули, чтобы зарегистрировать обработчики
from handlers.processors import lists  # noqa: F401
from handlers.processors import cards  # noqa: F401
from handlers.processors import notes  # noqa: F401
from handlers.processors import locations  # noqa: F401
from handlers.processors import documents  # noqa: F401
from handlers.processors import reminders  # noqa: F401
from handlers.processors import misc  # noqa: F401
from handlers.processors import birthdays  # noqa: F401
from handlers.processors import weather  # noqa: F401
from handlers.processors import widget  # noqa: F401
from handlers.processors import supplies  # noqa: F401
from handlers.processors import summary  # noqa: F401
from handlers.processors import calendar  # noqa: F401
from handlers.processors import games  # noqa: F401
from handlers.processors import crocodile  # noqa: F401
