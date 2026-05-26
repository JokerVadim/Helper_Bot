"""Helpers for displaying and editing AI memory records."""
from utils import md


def format_memory_rows(memories: list[dict], title: str = "🧠 *Моя память*") -> str:
    if not memories:
        return f"{title}\n\nПока ничего не найдено."

    lines = [f"{title} ({len(memories)} записей)\n"]
    for i, mem in enumerate(memories, 1):
        category = mem.get("category") or "общее"
        lines.append(f"{i}. `#{mem['id']}` [{md(category)}] *{md(mem['key'])}*: {md(mem['value'])}")
    lines.append("\n_Команды: `память поиск текст`, `память редактировать ID ключ = значение`, `память категория ID имя`_")
    return "\n".join(lines)


def format_pending_memories(memories: list[dict]) -> str:
    lines = ["🧠 *AI предлагает сохранить в память:*\n"]
    for i, mem in enumerate(memories, 1):
        category = mem.get("category") or "общее"
        lines.append(f"{i}. [{md(category)}] *{md(mem['key'])}*: {md(mem['value'])}")
    lines.append("\nНапиши `память подтвердить` или `память отмена`.")
    return "\n".join(lines)


def parse_memory_update(text: str):
    parts = text.strip().split(maxsplit=3)
    if len(parts) < 4 or not parts[2].isdigit() or "=" not in parts[3]:
        return None
    key, value = parts[3].split("=", 1)
    key = key.strip()
    value = value.strip()
    if not key or not value:
        return None
    return int(parts[2]), key, value


def parse_memory_category(text: str):
    parts = text.strip().split(maxsplit=3)
    if len(parts) < 4 or not parts[2].isdigit():
        return None
    category = parts[3].strip()
    if not category:
        return None
    return int(parts[2]), category
