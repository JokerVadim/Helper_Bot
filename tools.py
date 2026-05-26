"""Tool definitions for Groq Function Calling (Tool Use)."""

TOOLS = [
    # ─── Сумма (деньги) ──────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "get_summa",
            "description": "Получить текущую сумму денег пользователя",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_summa",
            "description": "Установить новую сумму денег пользователя",
            "parameters": {
                "type": "object",
                "properties": {
                    "amount": {"type": "number", "description": "Новая сумма денег"}
                },
                "required": ["amount"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_summa",
            "description": "Добавить или вычесть сумму денег. Для вычитания используйте отрицательное число.",
            "parameters": {
                "type": "object",
                "properties": {
                    "delta": {"type": "number", "description": "Сколько добавить (положительное) или вычесть (отрицательное)"}
                },
                "required": ["delta"]
            }
        }
    },

    # ─── Заметки ─────────────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "get_notes",
            "description": "Получить список всех заметок пользователя",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_note",
            "description": "Создать новую заметку",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Название заметки"},
                    "content": {"type": "string", "description": "Текст заметки"}
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "update_note",
            "description": "Обновить существующую заметку по ID",
            "parameters": {
                "type": "object",
                "properties": {
                    "note_id": {"type": "integer", "description": "ID заметки"},
                    "name": {"type": "string", "description": "Новое название (если нужно изменить)"},
                    "content": {"type": "string", "description": "Новый текст (если нужно изменить)"}
                },
                "required": ["note_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_note",
            "description": "Удалить заметку по ID",
            "parameters": {
                "type": "object",
                "properties": {
                    "note_id": {"type": "integer", "description": "ID заметки для удаления"}
                },
                "required": ["note_id"]
            }
        }
    },

    # ─── Списки ──────────────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "get_lists",
            "description": "Получить все списки пользователя",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_list_items",
            "description": "Получить элементы списка по ID",
            "parameters": {
                "type": "object",
                "properties": {
                    "list_id": {"type": "string", "description": "ID списка"}
                },
                "required": ["list_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_items",
            "description": "Добавить один или несколько элементов в список",
            "parameters": {
                "type": "object",
                "properties": {
                    "list_id": {"type": "string", "description": "ID списка"},
                    "items": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Список элементов для добавления"
                    }
                },
                "required": ["list_id", "items"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "check_item",
            "description": "Отметить элемент списка как выполненный (или снять отметку)",
            "parameters": {
                "type": "object",
                "properties": {
                    "list_id": {"type": "string", "description": "ID списка"},
                    "item_id": {"type": "integer", "description": "ID элемента"}
                },
                "required": ["list_id", "item_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_item",
            "description": "Удалить элемент из списка",
            "parameters": {
                "type": "object",
                "properties": {
                    "list_id": {"type": "string", "description": "ID списка"},
                    "item_id": {"type": "integer", "description": "ID элемента"}
                },
                "required": ["list_id", "item_id"]
            }
        }
    },

    # ─── Напоминания ─────────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "get_reminders",
            "description": "Получить все активные напоминания пользователя",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_reminder",
            "description": "Создать напоминание. fire_at — дата и время в формате YYYY-MM-DD HH:MM",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Текст напоминания"},
                    "fire_at": {"type": "string", "description": "Дата и время в формате YYYY-MM-DD HH:MM"},
                    "repeat_type": {
                        "type": "string",
                        "enum": ["none", "day", "week", "month", "year", "interval"],
                        "description": "Тип повторения: none — одноразовое, day — ежедневно, week — по дням, month — ежемесячно, year — ежегодно, interval — интервал"
                    }
                },
                "required": ["text", "fire_at"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_reminder",
            "description": "Удалить напоминание по ID",
            "parameters": {
                "type": "object",
                "properties": {
                    "reminder_id": {"type": "integer", "description": "ID напоминания"}
                },
                "required": ["reminder_id"]
            }
        }
    },

    # ─── Таймеры ─────────────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "create_timer",
            "description": "Создать таймер обратного отсчёта",
            "parameters": {
                "type": "object",
                "properties": {
                    "minutes": {"type": "integer", "description": "Количество минут"},
                    "text": {"type": "string", "description": "Подпись таймера"}
                },
                "required": ["minutes"]
            }
        }
    },

    # ─── Дни рождения ────────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "get_birthdays",
            "description": "Получить все дни рождения пользователя",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_birthday",
            "description": "Добавить день рождения. birth_date в формате DD.MM или DD.MM.YYYY",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Имя дня рождения"},
                    "birth_date": {"type": "string", "description": "Дата в формате DD.MM или DD.MM.YYYY"}
                },
                "required": ["name", "birth_date"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_birthday",
            "description": "Удалить день рождения по ID",
            "parameters": {
                "type": "object",
                "properties": {
                    "bday_id": {"type": "integer", "description": "ID дня рождения"}
                },
                "required": ["bday_id"]
            }
        }
    },

    # ─── Локации ─────────────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "get_locations",
            "description": "Получить все сохранённые локации пользователя",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_location",
            "description": "Удалить локацию по ID",
            "parameters": {
                "type": "object",
                "properties": {
                    "loc_id": {"type": "integer", "description": "ID локации"}
                },
                "required": ["loc_id"]
            }
        }
    },

    # ─── Файлы ───────────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "get_documents",
            "description": "Получить все файлы пользователя",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_document_tags",
            "description": "Получить все теги файлов с количеством",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },

    # ─── Курсы валют ────────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "get_currency_rate",
            "description": "Получить текущий курс валют (RUB, USD). Если указать summa, пересчитает сумму.",
            "parameters": {
                "type": "object",
                "properties": {
                    "currency": {
                        "type": "string",
                        "enum": ["RUB", "USD"],
                        "description": "Валюта: RUB — рубль, USD — доллар"
                    },
                    "summa": {
                        "type": "number",
                        "description": "Сумма для пересчёта (необязательно)"
                    }
                },
                "required": ["currency"]
            }
        }
    },
]


def handle_tool_call(tool_name: str, arguments: dict, user_id: int) -> str:
    """Execute a tool and return the result as a string.

    Примечание: в личных чатах user_id == chat_id, поэтому для всех
    операций с напоминаниями используем user_id как chat_id.
    """
    from db import db
    from datetime import datetime, timedelta

    # chat_id совпадает с user_id для личных чатов (бот персональный)
    chat_id = user_id

    # ── Сумма ────────────────────────────────────────────────────────────────
    if tool_name == "get_summa":
        value = db.get_summa(user_id)
        if value is None:
            return "0 (сумма не установлена)"
        return f"{value:,.0f}"

    if tool_name == "set_summa":
        amount = arguments.get("amount", 0)
        db.set_summa(user_id, amount)
        return f"Установлено: {amount:,.0f}"

    if tool_name == "add_summa":
        delta = arguments.get("delta", 0)
        current = db.get_summa(user_id) or 0
        new_val = current + delta
        db.set_summa(user_id, new_val)
        return f"Было: {current:,.0f}, изменение: {delta:+,.0f}, стало: {new_val:,.0f}"

    # ── Заметки ──────────────────────────────────────────────────────────────
    if tool_name == "get_notes":
        notes = db.get_notes(user_id)
        if not notes:
            return "Заметок нет"
        lines = []
        for n in notes:
            content_preview = (n.get("content") or "")[:50]
            lines.append(f"[{n['id']}] {n['name']}: {content_preview}")
        return "\n".join(lines)

    if tool_name == "create_note":
        name = arguments.get("name", "").strip()
        content = arguments.get("content", "").strip()
        if not name:
            return "Ошибка: название не может быть пустым"
        if db.note_exists(user_id, name):
            return f"Заметка '{name}' уже существует"
        db.save_note(user_id, name, content)
        return f"Заметка '{name}' создана"

    if tool_name == "update_note":
        note_id = arguments.get("note_id")
        name = arguments.get("name")
        content = arguments.get("content")
        notes = db.get_notes(user_id)
        note = None
        if isinstance(note_id, int):
            note = next((n for n in notes if n["id"] == note_id), None)
        if not note and isinstance(note_id, str):
            nid = note_id.lower().strip()
            note = next((n for n in notes if nid in n["name"].lower()), None)
        if not note:
            available = ", ".join(f"[{n['id']}] {n['name']}" for n in notes[:10]) or "нет заметок"
            return f"Заметка не найдена. Твои заметки: {available}"
        new_name = name or note["name"]
        new_content = content if content is not None else note.get("content", "")
        db.update_note(user_id, note["id"], new_name, new_content)
        return f"Заметка '{new_name}' обновлена"

    if tool_name == "delete_note":
        note_id = arguments.get("note_id")
        notes = db.get_notes(user_id)
        # Поиск по ID или по названию
        note = None
        if isinstance(note_id, int):
            note = next((n for n in notes if n["id"] == note_id), None)
        if not note and isinstance(note_id, str):
            nid = note_id.lower().strip()
            note = next((n for n in notes if nid in n["name"].lower()), None)
        if not note:
            available = ", ".join(f"[{n['id']}] {n['name']}" for n in notes[:10]) or "нет заметок"
            return f"Заметка не найдена. Твои заметки: {available}"
        db.delete_note(user_id, note["id"])
        return f"Заметка '{note['name']}' удалена"

    # ── Списки ───────────────────────────────────────────────────────────────
    if tool_name == "get_lists":
        lists = db.get_lists_for_user(user_id)
        if not lists:
            return "Списков нет"
        lines = []
        for lst in lists:
            items = db.get_items(lst["list_id"])
            total = len(items)
            done = sum(1 for i in items if i.get("checked"))
            lines.append(f"[{lst['list_id']}] {lst['name']} ({done}/{total})")
        return "\n".join(lines)

    if tool_name == "get_list_items":
        list_id = arguments.get("list_id", "")
        items = db.get_items(list_id)
        if not items:
            return "Список пуст или не найден"
        lines = []
        for item in items:
            ck = "☑" if item.get("checked") else "☐"
            emoji = item.get("emoji", "📌") or "📌"
            lines.append(f"{ck} [{item['id']}] {emoji} {item['item']}")
        return "\n".join(lines)

    if tool_name == "add_items":
        list_id = arguments.get("list_id", "")
        items = arguments.get("items", [])
        if not items:
            return "Нечего добавлять"
        added = 0
        for item_text in items:
            item_text = item_text.strip()
            if item_text and not db.item_exists(list_id, item_text):
                db.add_item(list_id, user_id, item_text)
                added += 1
        return f"Добавлено {added} элементов"

    if tool_name == "check_item":
        list_id = arguments.get("list_id", "")
        item_id = arguments.get("item_id")
        result = db.toggle_item_checked_by_id(list_id, item_id)
        if result is None:
            return "Элемент не найден"
        return "Отмечено ☑" if result else "Отметка снята ☐"

    if tool_name == "delete_item":
        list_id = arguments.get("list_id", "")
        item_id = arguments.get("item_id")
        items = db.get_items(list_id)
        item_idx = next((i for i, it in enumerate(items) if it["id"] == item_id), None)
        if item_idx is None:
            return "Элемент не найден"
        db.delete_item_by_index(list_id, item_idx)
        return f"Элемент '{items[item_idx]['item']}' удалён"

    # ── Напоминания ──────────────────────────────────────────────────────────
    if tool_name == "get_reminders":
        from handlers.session import reminders as memory_reminders
        r_list = memory_reminders.get(chat_id, [])
        if not r_list:
            return "Напоминаний нет"
        lines = []
        for r in r_list:
            if r.get("is_timer") or r.get("delivered"):
                continue
            time_str = r["time"].strftime("%d.%m %H:%M") if r.get("time") else "?"
            lines.append(f"[{r['id']}] {r['text']} — {time_str}")
        return "\n".join(lines) if lines else "Напоминаний нет"

    if tool_name == "create_reminder":
        text = arguments.get("text", "").strip()
        fire_at_str = arguments.get("fire_at", "")
        repeat_type = arguments.get("repeat_type", "none")
        if not text or not fire_at_str:
            return "Ошибка: нужны текст и дата"
        try:
            fire_at = datetime.strptime(fire_at_str, "%Y-%m-%d %H:%M")
        except ValueError:
            return "Ошибка: неверный формат даты. Используй YYYY-MM-DD HH:MM"
        from handlers.reminders import next_reminder_id, auto_assign_reminder_tags
        rid = next_reminder_id(chat_id)
        db.save_reminder(chat_id, rid, text, fire_at, False, repeat_type)
        auto_assign_reminder_tags(chat_id, rid, repeat_type)
        from handlers.session import _store_memory_reminder
        _store_memory_reminder(chat_id, {
            "id": rid, "text": text, "time": fire_at,
            "repeat_type": repeat_type, "is_timer": False,
            "minutes": 0, "repeat_days": "", "delivered": False, "job": None,
        })
        return f"Напоминание #{rid} создано: {text} на {fire_at_str}"

    if tool_name == "delete_reminder":
        rid = arguments.get("reminder_id")
        from handlers.session import reminders as memory_reminders, _remove_memory_reminder
        r_list = memory_reminders.get(chat_id, [])
        item = None
        if isinstance(rid, int):
            item = next((r for r in r_list if r["id"] == rid), None)
        if not item and isinstance(rid, str):
            rid_lower = rid.lower().strip()
            item = next((r for r in r_list if rid_lower in r.get("text", "").lower()), None)
        if not item:
            available = ", ".join(f"[{r['id']}] {r.get('text','?')}" for r in r_list[:10]) or "нет напоминаний"
            return f"Напоминание не найдено. Твои напоминания: {available}"
        _remove_memory_reminder(chat_id, item["id"])
        db.delete_reminder(chat_id, item["id"])
        return f"Напоминание #{item['id']} '{item.get('text','')}' удалено"

    # ── Таймеры ──────────────────────────────────────────────────────────────
    if tool_name == "create_timer":
        minutes = arguments.get("minutes", 0)
        text = arguments.get("text", "⏱ Таймер")
        if minutes <= 0:
            return "Ошибка: время должно быть больше 0"
        fire_at = datetime.now() + timedelta(minutes=minutes)
        from handlers.reminders import next_reminder_id
        rid = next_reminder_id(chat_id)
        db.save_reminder(chat_id, rid, text, fire_at, True, "none")
        from handlers.session import _store_memory_reminder
        _store_memory_reminder(chat_id, {
            "id": rid, "text": text, "time": fire_at,
            "repeat_type": "none", "is_timer": True,
            "minutes": 0, "repeat_days": "", "delivered": False, "job": None,
        })
        return f"Таймер #{rid} на {minutes} мин. запущен"

    # ── Дни рождения ─────────────────────────────────────────────────────────
    if tool_name == "get_birthdays":
        bdays = db.get_birthdays(user_id)
        if not bdays:
            return "Дней рождения нет"
        lines = []
        for b in bdays:
            lines.append(f"[{b['id']}] {b['name']} — {b['birth_date']}")
        return "\n".join(lines)

    if tool_name == "add_birthday":
        name = arguments.get("name", "").strip()
        birth_date = arguments.get("birth_date", "").strip()
        if not name or not birth_date:
            return "Ошибка: нужны имя и дата"
        if db.birthday_exists(user_id, name):
            return f"День рождения '{name}' уже есть"
        db.save_birthday(user_id, name, birth_date)
        return f"День рождения '{name}' добавлен ({birth_date})"

    if tool_name == "delete_birthday":
        bday_id = arguments.get("bday_id")
        bdays = db.get_birthdays(user_id)
        bday = None
        if isinstance(bday_id, int):
            bday = next((b for b in bdays if b["id"] == bday_id), None)
        if not bday and isinstance(bday_id, str):
            bid = bday_id.lower().strip()
            bday = next((b for b in bdays if bid in b["name"].lower()), None)
        if not bday:
            available = ", ".join(f"[{b['id']}] {b['name']}" for b in bdays[:10]) or "нет дней рождения"
            return f"День рождения не найден. Твои дни рождения: {available}"
        db.delete_birthday(user_id, bday["id"])
        return f"День рождения '{bday['name']}' удалён"

    # ── Локации ──────────────────────────────────────────────────────────────
    if tool_name == "get_locations":
        locs = db.get_locations(user_id)
        if not locs:
            return "Локаций нет"
        lines = []
        for loc in locs:
            lines.append(f"[{loc['id']}] {loc['name']} — {loc['latitude']:.5f}, {loc['longitude']:.5f}")
        return "\n".join(lines)

    if tool_name == "delete_location":
        loc_id = arguments.get("loc_id")
        locs = db.get_locations(user_id)
        loc = None
        if isinstance(loc_id, int):
            loc = next((l for l in locs if l["id"] == loc_id), None)
        if not loc and isinstance(loc_id, str):
            lid = loc_id.lower().strip()
            loc = next((l for l in locs if lid in l["name"].lower()), None)
        if not loc:
            available = ", ".join(f"[{l['id']}] {l['name']}" for l in locs[:10]) or "нет локаций"
            return f"Локация не найдена. Твои локации: {available}"
        db.delete_location(user_id, loc["id"])
        return f"Локация '{loc['name']}' удалена"

    # ── Файлы ────────────────────────────────────────────────────────────
    if tool_name == "get_documents":
        docs = db.get_documents(user_id)
        if not docs:
            return "Файлов нет"
        lines = []
        for d in docs:
            lines.append(f"[{d['id']}] {d['name']}")
        return "\n".join(lines)

    if tool_name == "get_document_tags":
        tags = db.get_document_tags_with_counts(user_id)
        if not tags:
            return "Тегов нет"
        lines = []
        for t in tags:
            lines.append(f"[{t['id']}] {t['name']} ({t['count']})")
        return "\n".join(lines)

    # ── Курсы валют ──────────────────────────────────────────────────────────
    if tool_name == "get_currency_rate":
        from ai import _fetch_rub_direct, _fetch_usd_direct
        currency = arguments.get("currency", "").upper()
        summa = arguments.get("summa")
        if currency == "RUB":
            return _fetch_rub_direct(summa)
        elif currency == "USD":
            return _fetch_usd_direct(summa)
        else:
            return "Неизвестная валюта. Доступны: RUB, USD"

    return f"Неизвестный инструмент: {tool_name}"
