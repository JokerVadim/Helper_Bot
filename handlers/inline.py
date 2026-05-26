"""Inline query handler — курсы валют, списки, заметки, погода, дни рождения через @bot."""

import asyncio
import logging

from telegram import InlineQueryResultArticle, InputTextMessageContent
from telegram.ext import InlineQueryHandler

from ai import _fetch_rub_direct, _fetch_usd_direct
from utils import _pad, is_authorized, md
from db import (
    db_get_lists_for_user, db_get_items,
    db_get_notes,
    db_get_weather_locations,
    db_get_birthdays,
    db_get_locations,
)
from handlers.processors.birthdays import _format_bday_short, _sort_birthdays, _calc_age, MONTH_NAMES
from handlers.processors.weather import (
    fetch_weather, _get_city_name, _wmo_icon, _wmo_desc, _wind_dir,
)
from utils.list_display import format_list_display

logger = logging.getLogger(__name__)

CACHE_TIME = 60


async def inline_handler_main(update, context):
    """Main inline query handler — dispatches to section-specific logic."""
    query = update.inline_query
    user = query.from_user

    if not is_authorized(user.id):
        await query.answer([], cache_time=300)
        return

    user_text = (query.query or "").strip().lower()

    # ── Маршрутизация ──
    if not user_text or user_text in ("help", "start", "меню", "помощь", "что"):
        results = _build_help_results()

    elif any(w in user_text for w in ("usd", "доллар", "$", "dollar")):
        results = await _build_currency_results(show_rub=False, show_usd=True)

    elif any(w in user_text for w in ("rub", "руб", "₽", "ruble")):
        results = await _build_currency_results(show_rub=True, show_usd=False)

    elif any(w in user_text for w in ("курс", "валюта", "rate", "currency")):
        results = await _build_currency_results(show_rub=True, show_usd=True)

    elif any(w in user_text for w in ("список", "list", "списки", "lists")):
        results = await _build_lists_results(user.id)

    elif any(w in user_text for w in ("заметк", "note", "заметки", "notes")):
        results = await _build_notes_results(user.id)

    elif any(w in user_text for w in ("погод", "weather", "🌤", "погода")):
        results = await _build_weather_results(user.id)

    elif any(w in user_text for w in ("днюх", "день рожд", "birthday", "др", "день рождения")):
        results = await _build_birthdays_results(user.id)

    elif any(w in user_text for w in ("локац", "location", "место", "места")):
        results = await _build_locations_results(user.id)

    else:
        # Непонятный запрос — курсы + подсказка
        results = await _build_currency_results(show_rub=True, show_usd=True)
        if len(results) < 10:
            results.append(
                InlineQueryResultArticle(
                    id="help_fallback",
                    title="❓ Помощь",
                    description="Введи @bot список, заметки, погода, днюха, курс, локации",
                    input_message_content=InputTextMessageContent(
                        _pad("Доступные inline-запросы:\n\n"
                             "• `@bot курс` — курсы валют\n"
                             "• `@bot список` — твои списки\n"
                             "• `@bot заметки` — твои заметки\n"
                             "• `@bot погода` — погода\n"
                             "• `@bot днюха` — дни рождения\n"
                             "• `@bot локации` — избранные места\n"
                             "• `@bot rub` / `@bot usd` — отдельные валюты"),
                        parse_mode="Markdown",
                    ),
                )
            )

    await query.answer(results, cache_time=CACHE_TIME, is_personal=True)


# ═══════════════════════════════════════════════════════════════════════════════
# Help
# ═══════════════════════════════════════════════════════════════════════════════

def _build_help_results() -> list[InlineQueryResultArticle]:
    return [
        InlineQueryResultArticle(
            id="help_currency",
            title="💱 Курс валют",
            description="@bot курс / rub / usd",
            input_message_content=InputTextMessageContent(
                _pad("💱 *Курсы валют*\n\nВведи:\n• `@bot rub` — курс рубля\n• `@bot usd` — курс доллара\n• `@bot курс` — оба курса"),
                parse_mode="Markdown",
            ),
        ),
        InlineQueryResultArticle(
            id="help_lists",
            title="📋 Списки",
            description="Посмотреть списки. @bot список",
            input_message_content=InputTextMessageContent(
                _pad("📋 *Списки*\n\nВведи `@bot список`, чтобы увидеть свои списки."),
                parse_mode="Markdown",
            ),
        ),
        InlineQueryResultArticle(
            id="help_notes",
            title="📝 Заметки",
            description="Найти заметки. @bot заметки",
            input_message_content=InputTextMessageContent(
                _pad("📝 *Заметки*\n\nВведи `@bot заметки`, чтобы увидеть свои заметки."),
                parse_mode="Markdown",
            ),
        ),
        InlineQueryResultArticle(
            id="help_weather",
            title="🌤 Погода",
            description="Погода для твоих локаций. @bot погода",
            input_message_content=InputTextMessageContent(
                _pad("🌤 *Погода*\n\nВведи `@bot погода`, чтобы увидеть погоду для своих локаций."),
                parse_mode="Markdown",
            ),
        ),
        InlineQueryResultArticle(
            id="help_birthdays",
            title="🎂 Дни рождения",
            description="Ближайшие дни рождения. @bot днюха",
            input_message_content=InputTextMessageContent(
                _pad("🎂 *Дни рождения*\n\nВведи `@bot днюха`, чтобы увидеть дни рождения."),
                parse_mode="Markdown",
            ),
        ),
        InlineQueryResultArticle(
            id="help_locations",
            title="📍 Локации",
            description="Избранные места. @bot локации",
            input_message_content=InputTextMessageContent(
                _pad("📍 *Локации*\n\nВведи `@bot локации`, чтобы увидеть избранные места."),
                parse_mode="Markdown",
            ),
        ),
    ]


# ═══════════════════════════════════════════════════════════════════════════════
# Currency
# ═══════════════════════════════════════════════════════════════════════════════

async def _build_currency_results(show_rub: bool, show_usd: bool) -> list[InlineQueryResultArticle]:
    results = []

    if show_rub:
        rub_text = await asyncio.to_thread(_fetch_rub_direct)
        if rub_text:
            results.append(InlineQueryResultArticle(
                id="rub",
                title="💱 Курс рубля (Kapitalbank)",
                description=_strip_md_for_desc(rub_text),
                input_message_content=InputTextMessageContent(rub_text, parse_mode="Markdown"),
            ))

    if show_usd:
        usd_text = await asyncio.to_thread(_fetch_usd_direct)
        if usd_text:
            results.append(InlineQueryResultArticle(
                id="usd",
                title="💲 Курс доллара (Agrobank)",
                description=_strip_md_for_desc(usd_text),
                input_message_content=InputTextMessageContent(usd_text, parse_mode="Markdown"),
            ))

    if not results:
        results.append(InlineQueryResultArticle(
            id="currency_error",
            title="⚠️ Курсы временно недоступны",
            description="Попробуй позже",
            input_message_content=InputTextMessageContent(_pad("⚠️ Не удалось получить курсы валют. Попробуй позже.")),
        ))

    return results


# ═══════════════════════════════════════════════════════════════════════════════
# Lists
# ═══════════════════════════════════════════════════════════════════════════════

async def _build_lists_results(user_id: int) -> list[InlineQueryResultArticle]:
    lists = await db_get_lists_for_user(user_id)
    results = []

    if not lists:
        results.append(InlineQueryResultArticle(
            id="lists_empty",
            title="📋 Нет списков",
            description="Создай список в чате с ботом",
            input_message_content=InputTextMessageContent(_pad("📋 У тебя пока нет списков. Создай их в чате с ботом.")),
        ))
        return results

    for lst in lists[:10]:
        list_id = lst["list_id"]
        name = lst["name"]
        items = await db_get_items(list_id)

        display = format_list_display(name, items)
        completed = sum(1 for it in items if it.get("checked"))
        total = len(items)

        lines = [f"📋 *{md(name)}*", f"_{completed}/{total}_\n"]
        for item in items:
            ck = "☑" if item.get("checked") else "☐"
            emoji = item.get("emoji", "📌") or "📌"
            lines.append(f"{ck} {emoji} {md(item['item'])}")

        results.append(InlineQueryResultArticle(
            id=f"list_{list_id}",
            title=display,
            description=f"{completed}/{total} элементов",
            input_message_content=InputTextMessageContent(_pad("\n".join(lines)), parse_mode="Markdown"),
        ))

    return results


# ═══════════════════════════════════════════════════════════════════════════════
# Notes
# ═══════════════════════════════════════════════════════════════════════════════

async def _build_notes_results(user_id: int) -> list[InlineQueryResultArticle]:
    notes = await db_get_notes(user_id)
    results = []

    if not notes:
        results.append(InlineQueryResultArticle(
            id="notes_empty",
            title="📝 Нет заметок",
            description="Создай заметку в чате с ботом",
            input_message_content=InputTextMessageContent(_pad("📝 У тебя пока нет заметок. Создай их в чате с ботом.")),
        ))
        return results

    for note in notes[:10]:
        name = note["name"]
        content = note.get("content", "")
        desc = content[:70].replace("\n", " ").strip() if content else "(пусто)"

        msg_text = f"📝 *{md(name)}*"
        if content:
            msg_text += f"\n\n{md(content)}"

        results.append(InlineQueryResultArticle(
            id=f"note_{note['id']}",
            title=f"📝 {name}",
            description=desc,
            input_message_content=InputTextMessageContent(_pad(msg_text), parse_mode="Markdown"),
        ))

    return results


# ═══════════════════════════════════════════════════════════════════════════════
# Weather
# ═══════════════════════════════════════════════════════════════════════════════

async def _build_weather_results(user_id: int) -> list[InlineQueryResultArticle]:
    locs = await db_get_weather_locations(user_id)
    results = []

    if not locs:
        results.append(InlineQueryResultArticle(
            id="weather_empty",
            title="🌤 Нет локаций",
            description="Добавь локацию в разделе Погода бота",
            input_message_content=InputTextMessageContent(
                _pad("🌤 У тебя пока нет сохранённых локаций для погоды.\n\n"
                     "Добавь их в чате с ботом: Меню → Погода → ✚ Добавить")
            ),
        ))
        return results

    for loc in locs[:5]:
        loc_name = loc["name"]
        is_primary = loc.get("is_primary")
        label = f"⭐ {loc_name}" if is_primary else loc_name

        try:
            city = await asyncio.to_thread(_get_city_name, loc["latitude"], loc["longitude"])
            data = await fetch_weather(loc["latitude"], loc["longitude"], days=1, hourly=False)

            if data and data.get("current"):
                curr = data["current"]
                temp = curr.get("temperature_2m")
                wcode = curr.get("weather_code", 0)
                icon = _wmo_icon(wcode)
                desc = _wmo_desc(wcode)

                summary = f"{icon} {temp:+.0f}°C, {desc}"
                if city:
                    summary += f" ({city})"

                # Полный текст для отправки
                text_parts = [f"🌤 *Погода*: {md(loc_name)}"]
                if city:
                    text_parts[0] += f" ({city})"

                text_parts.append("")
                text_parts.append("*━━━ СЕЙЧАС ━━━*")
                text_parts.append(f"{icon}  {temp:+.0f}°C  {desc}")

                feels = curr.get("apparent_temperature")
                if feels is not None:
                    text_parts.append(f"Ощущается: {feels:+.0f}°C")

                humidity = curr.get("relative_humidity_2m")
                wind = curr.get("wind_speed_10m")
                if humidity is not None:
                    text_parts.append(f"💧 {humidity}%")
                if wind is not None:
                    wdir = curr.get("wind_direction_10m")
                    wdir_str = _wind_dir(wdir) if wdir is not None else "?"
                    text_parts.append(f"🌪️ {wind:.0f} м/с, {wdir_str}")

                content = "\n".join(text_parts)

                results.append(InlineQueryResultArticle(
                    id=f"weather_{loc['id']}",
                    title=f"🌤 {label}",
                    description=summary,
                    input_message_content=InputTextMessageContent(_pad(content), parse_mode="Markdown"),
                ))
            else:
                results.append(InlineQueryResultArticle(
                    id=f"weather_{loc['id']}",
                    title=f"🌤 {label}",
                    description="⚠️ Нет данных",
                    input_message_content=InputTextMessageContent(
                        _pad(f"⚠️ Не удалось получить погоду для *{md(loc_name)}*."),
                        parse_mode="Markdown",
                    ),
                ))
        except Exception as e:
            logger.warning(f"Weather inline error for {loc_name}: {e}")
            results.append(InlineQueryResultArticle(
                id=f"weather_{loc['id']}",
                title=f"🌤 {label}",
                description="⚠️ Ошибка",
                input_message_content=InputTextMessageContent(
                    _pad(f"⚠️ Ошибка при получении погоды для *{md(loc_name)}*."),
                    parse_mode="Markdown",
                ),
            ))

    return results


# ═══════════════════════════════════════════════════════════════════════════════
# Locations
# ═══════════════════════════════════════════════════════════════════════════════

async def _build_locations_results(user_id: int) -> list[InlineQueryResultArticle]:
    locs = await db_get_locations(user_id)
    results = []

    if not locs:
        results.append(InlineQueryResultArticle(
            id="locs_empty",
            title="📍 Нет локаций",
            description="Добавь локацию в чате с ботом",
            input_message_content=InputTextMessageContent(_pad("📍 У тебя пока нет сохранённых локаций.\n\nДобавь их в чате с ботом: Меню → Локации → ✚ Добавить")),
        ))
        return results

    for loc in locs[:10]:
        name = loc["name"]
        lat = loc["latitude"]
        lon = loc["longitude"]

        maps_url = f"https://www.google.com/maps?q={lat},{lon}"

        content = _pad(f"📍 *{md(name)}*\n\n🌐 [{lat:.5f}, {lon:.5f}]({maps_url})")

        results.append(InlineQueryResultArticle(
            id=f"loc_{loc['id']}",
            title=f"📍 {name}",
            description=f"{lat:.4f}, {lon:.4f}",
            input_message_content=InputTextMessageContent(content, parse_mode="Markdown", disable_web_page_preview=True),
        ))

    return results


# ═══════════════════════════════════════════════════════════════════════════════
# Birthdays
# ═══════════════════════════════════════════════════════════════════════════════

async def _build_birthdays_results(user_id: int) -> list[InlineQueryResultArticle]:
    birthdays = await db_get_birthdays(user_id)
    results = []

    if not birthdays:
        results.append(InlineQueryResultArticle(
            id="bday_empty",
            title="🎂 Нет дней рождения",
            description="Добавь дни рождения в чате с ботом",
            input_message_content=InputTextMessageContent(
                _pad("🎂 У тебя пока нет сохранённых дней рождения.\n\n"
                     "Добавь их в чате с ботом: Меню → Дни рождения → ✚ Добавить")
            ),
        ))
        return results

    sorted_bdays = _sort_birthdays(birthdays)

    for b in sorted_bdays[:10]:
        label = _format_bday_short(b["name"], b["birth_date"])

        parts = b["birth_date"].split(".")
        day, month = int(parts[0]), int(parts[1])
        month_name = MONTH_NAMES.get(month, "")

        age = _calc_age(b["birth_date"])
        age_text = f"\nВозраст: {age} лет" if age is not None else ""

        content = _pad(f"🎂 *{md(b['name'])}*\n\n📅 {day} {month_name}{age_text}")

        results.append(InlineQueryResultArticle(
            id=f"bday_{b['id']}",
            title=label,
            description="🎉 Сегодня!" if _days_until(b["birth_date"]) == 0 else "",
            input_message_content=InputTextMessageContent(content, parse_mode="Markdown"),
        ))

    return results


def _days_until(birth_date: str) -> int | None:
    """Количество дней до следующего дня рождения."""
    from handlers.processors.birthdays import _days_until_next_birthday
    return _days_until_next_birthday(birth_date)


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _strip_md_for_desc(text: str) -> str:
    """Убрать Markdown-разметку и скрытые символы для поля description."""
    result = text.replace("*", "")
    result = result.replace("_", "")
    result = result.replace("`", "")
    result = result.replace("\u3164", "").strip()
    return result[:70]


# Экспортируем handler для регистрации в bot.py
inline_handler = InlineQueryHandler(inline_handler_main)
