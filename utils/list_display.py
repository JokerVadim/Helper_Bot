"""Display helpers for user lists."""

LIST_EMOJI_MAP = {
    "покуп": "🛒",
    "магазин": "🛒",
    "продукт": "🛒",
    "учеб": "📚",
    "работ": "💼",
    "фильм": "🎬",
    "игр": "🎮",
    "иде": "💡",
    "поезд": "✈️",
    "дом": "🏠",
    "спорт": "🏋️",
    "музык": "🎵",
}


def get_list_emoji(name: str) -> str:
    """Return an emoji that matches the list name."""
    normalized = str(name or "").lower().replace("ё", "е")
    for keyword, emoji in LIST_EMOJI_MAP.items():
        if keyword in normalized:
            return emoji
    return "📋"


def get_list_stats(items: list[dict]) -> tuple[int, int, str]:
    """Return completed count, total count, and progress bar."""
    total = len(items)
    completed = sum(1 for item in items if item.get("checked"))

    if total == 0:
        bar = "□□□□□□□□□□"
    elif total <= 10:
        # Каждый элемент = 1 квадрат
        bar = "■" * completed + "□" * (total - completed)
    else:
        # Проценты: 10 квадратов, каждый = 10%
        filled = round(10 * completed / total)
        bar = "■" * filled + "□" * (10 - filled)

    return completed, total, bar


def format_list_display(name: str, items: list[dict]) -> str:
    """Format a list name with semantic emoji and completion stats."""
    completed, total, indicator = get_list_stats(items)
    return f"{get_list_emoji(name)} {name} {indicator} {completed}/{total}"
