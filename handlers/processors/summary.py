"""Summary (Сводка) section — aggregated view of selected sections.

Конфигурация хранится в таблице summary_config как JSON (список ключей разделов
или dict с полями "sections" и "sort_mode").
Разделы можно включать/выключать чекбоксами и менять их порядок через сортировку.
"""
import asyncio
import logging
import re
from datetime import date, datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from keyboards import btn_menu
from handlers.processors import register_callback_handler
from utils import md, _pad

logger = logging.getLogger(__name__)

# Доступные разделы: (ключ, эмодзи, название)
SECTIONS = [
    ("reminders", "⏰", "Напоминания"),
    ("birthdays", "🎂", "Дни рождения"),
    ("weather", "🌤", "Погода"),
    ("summa", "💰", "Сумма"),
    ("rate", "🏦", "Курс"),
    ("supplies", "📦", "Расходники"),
    ("lists", "📋", "Списки"),
]

SECTIONS_DICT: dict[str, tuple[str, str]] = {k: (e, n) for k, e, n in SECTIONS}


def _cycle_sort_mode(current: str) -> str:
    """Циклический переключатель: "" → "up" → "down" → ""."""
    return {"": "up", "up": "down", "down": ""}[current]


async def _fetch_section_data(user_id: int, section_key: str, db) -> str:
    try:
        if section_key == "reminders":
            from handlers.reminders import reminders
            items = [r for r in reminders.get(user_id, [])
                     if not r.get("is_timer") and not r.get("delivered")]
            today = datetime.now().date()
            today_items = [r for r in items if r["time"].date() == today]
            if not today_items:
                return ""
            lines = []
            for r in sorted(today_items, key=lambda x: x["time"]):
                t = r["time"].strftime("%H:%M")
                lines.append(f"• {t} {md(r['text'])}")
            return "⏰ *Напоминания:*\n" + "\n".join(lines)

        elif section_key == "birthdays":
            bdays = await asyncio.to_thread(db.get_birthdays, user_id)
            if not bdays:
                return ""
            now = datetime.now()
            today = date(now.year, now.month, now.day)
            lines_today = []
            lines_soon = []
            for b in bdays:
                parts = b["birth_date"].split(".")
                if len(parts) < 2:
                    continue
                bd_month, bd_day = int(parts[1]), int(parts[0])
                bd_this_year = date(now.year, bd_month, bd_day)
                diff = (bd_this_year - today).days
                if diff < 0:
                    bd_this_year = date(now.year + 1, bd_month, bd_day)
                    diff = (bd_this_year - today).days
                label = f"{b['name']} - {parts[0]}.{parts[1]}"
                if diff == 0:
                    lines_today.append(label)
                elif 1 <= diff <= 3:
                    lines_soon.append(label)
            result = ""
            if lines_today:
                result += "🎂 *Сегодня день рождения:*\n" + "\n".join(f"🎉 {l}" for l in lines_today)
            if lines_soon:
                if result:
                    result += "\n\n"
                result += "*Скоро день рождения:*\n" + "\n".join(lines_soon)
            return result

        elif section_key == "weather":
            from handlers.processors.weather import (
                fetch_weather, fetch_air_quality, _wmo_icon, _wmo_desc, _wind_dir,
                _uv_indicator, _pressure_indicator, format_air_quality,
            )
            locations = await asyncio.to_thread(db.get_weather_locations, user_id)
            if not locations:
                return ""
            loc = next((l for l in locations if l.get("is_primary")), locations[0])
            data = await fetch_weather(loc["latitude"], loc["longitude"], days=1, hourly=False)
            loc_line = f"🌤 *Погода:* {md(loc['name'])}"
            if not data or not data.get("current"):
                return loc_line
            curr = data["current"]
            temp = curr.get("temperature_2m")
            wcode = curr.get("weather_code", 0)
            humidity = curr.get("relative_humidity_2m")
            wind = curr.get("wind_speed_10m")
            wdir = curr.get("wind_direction_10m")
            icon = _wmo_icon(wcode)
            desc = _wmo_desc(wcode)
            lines = [
                loc_line,
                f"{icon} {temp:+.0f}°C, {desc}",
            ]
            if humidity is not None:
                lines.append(f"💧 Влажность: {humidity}%")
            if wind is not None:
                wdir_str = _wind_dir(wdir) if wdir is not None else "?"
                lines.append(f"🌪 Ветер: {wind:.0f} м/с {wdir_str}")
            uv = curr.get("uv_index")
            if uv is not None:
                lines.append(f"☀️ UV — {uv:.1f} {_uv_indicator(uv)}")
            pressure = curr.get("surface_pressure")
            if pressure is not None:
                lines.append(f"🌡️ hPa — {pressure:.0f} {_pressure_indicator(pressure)}")
            try:
                aqi_data = await fetch_air_quality(loc["latitude"], loc["longitude"])
                if aqi_data:
                    aqi_text = format_air_quality(aqi_data)
                    if aqi_text:
                        lines.append(f"🌬️ {aqi_text}")
            except Exception:
                pass
            daily = data.get("daily", {})
            if daily and daily.get("temperature_2m_max") and daily.get("temperature_2m_min"):
                max_t = daily["temperature_2m_max"][0]
                min_t = daily["temperature_2m_min"][0]
                lines.append(f"🌡 {max_t:+.0f}°C / {min_t:+.0f}°C")
            return "\n".join(lines)

        elif section_key == "summa":
            val = await asyncio.to_thread(db.get_summa, user_id)
            if val is not None:
                formatted = f"{val:,.0f}".replace(",", " ")
                return f"💰 *Сумма:* {formatted} сум"
            return ""

        elif section_key == "rate":
            import cloudscraper
            import requests
            summa_val = (await asyncio.to_thread(db.get_summa, user_id)) or 0
            parts = []
            # RUB (Kapitalbank)
            try:
                def _get_rub():
                    scraper = cloudscraper.create_scraper()
                    html = scraper.get(
                        "https://www.kapitalbank.uz/ru/services/exchange-rates/", timeout=15
                    ).text
                    m = re.search(
                        r"\[code\]\s*=>\s*RUB\s*\[course_buy\]\s*=>\s*(\d+)\s*\[course_sell\]\s*=>\s*(\d+)",
                        html, re.DOTALL
                    )
                    return (m.group(1), m.group(2)) if m else None
                rub = await asyncio.to_thread(_get_rub)
                if rub:
                    lines = ["💱 *Курс рубля (Kapitalbank)*"]
                    lines.append(f"📉 Покупка: {rub[0]} сум")
                    lines.append(f"📈 Продажа: {rub[1]} сум")
                    sell_int = int(rub[1])
                    if sell_int > 0 and summa_val:
                        conv = (int(summa_val) // sell_int // 1000) * 1000
                        conv_str = f"{conv:,}".replace(",", " ")
                        lines.append(f"💰 Доступно: {conv_str} руб")
                    parts.append("\n".join(lines))
            except Exception:
                pass
            # USD (Agrobank)
            try:
                def _get_usd():
                    r = requests.get(
                        "https://agrobank.uz/api/v1/?action=pages&code=uz%2Fperson%2Fexchange_rates",
                        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
                        timeout=10,
                    )
                    r.raise_for_status()
                    for section in r.json().get("data", {}).get("sections", []):
                        for block in section.get("blocks", []):
                            if block.get("type") == "currency-rates":
                                for item in block.get("content", {}).get("items", []):
                                    if item.get("alpha3") == "USD":
                                        return (item.get("buy"), item.get("sale"))
                    return None
                usd = await asyncio.to_thread(_get_usd)
                if usd:
                    buy_str = f"{int(usd[0]):,}".replace(",", " ")
                    sell_str = f"{int(usd[1]):,}".replace(",", " ")
                    lines = ["💲 *Курс доллара (Agrobank)*"]
                    lines.append(f"📉 Покупка: {buy_str} сум")
                    lines.append(f"📈 Продажа: {sell_str} сум")
                    if int(usd[1]) > 0 and summa_val:
                        conv = int(summa_val) // int(usd[1])
                        conv_str = f"{conv:,}".replace(",", " ")
                        lines.append(f"💰 Доступно: {conv_str} USD")
                    parts.append("\n".join(lines))
            except Exception:
                pass
            if not parts:
                return ""
            return "\n\n".join(parts)

        elif section_key == "supplies":
            supplies = await asyncio.to_thread(db.get_supplies, user_id)
            low = [s for s in supplies if s["min_quantity"] > 0 and s["quantity"] <= s["min_quantity"]]
            if not low:
                return ""
            lines = [f"• {md(s['name'])} - {s['quantity']}" for s in low]
            return "📦 *У вас заканчиваются:*\n" + "\n".join(lines)

        elif section_key == "lists":
            lists_data = await asyncio.to_thread(db.get_lists_for_user, user_id)
            if not lists_data:
                return ""
            lines = []
            for lst in lists_data:
                items = await asyncio.to_thread(db.get_items, lst["list_id"])
                total = len(items)
                checked = sum(1 for i in items if i.get("checked"))
                lines.append(f"• {md(lst['name'])} ({checked}/{total})")
            return "📋 *Списки:*\n" + "\n".join(lines)

    except Exception as e:
        logger.warning(f"Summary fetch {section_key}: {e}")

    return ""


# ═══════════════════════════════════════════════════════════════════════════════
# Show Summary
# ═══════════════════════════════════════════════════════════════════════════════

@register_callback_handler("open_summary")
async def cb_open_summary(query, context, data, user, chat_id, bot):
    await show_summary(query, user.id, chat_id, bot)


@register_callback_handler("summary_toggle_")
async def cb_summary_toggle(query, context, data, user, chat_id, bot):
    section_key = data[len("summary_toggle_"):]
    from db import db
    config = db.get_summary_config(user.id)
    if section_key in config:
        config.remove(section_key)
    else:
        config.append(section_key)
    db.save_summary_config(user.id, config)
    await show_summary(query, user.id, chat_id, bot)


@register_callback_handler("summary_sort_cycle")
async def cb_summary_sort_cycle(query, context, data, user, chat_id, bot):
    from db import db
    sort_mode = db.get_summary_sort_mode(user.id)
    sort_mode = _cycle_sort_mode(sort_mode)
    db.save_summary_sort_mode(user.id, sort_mode)
    await show_summary(query, user.id, chat_id, bot)


@register_callback_handler("summary_move_")
async def cb_summary_move(query, context, data, user, chat_id, bot):
    """Переместить раздел вверх/вниз."""
    from db import db
    parts = data.split("_")
    if len(parts) < 3:
        return
    direction = parts[-1]  # "up" or "down"
    # section_key может содержать подчёркивания, поэтому берём всё между первыми двумя и последним
    section_key = "_".join(parts[2:-1])

    config = db.get_summary_config(user.id)
    if section_key not in config:
        return
    idx = config.index(section_key)
    if direction == "up" and idx > 0:
        config[idx], config[idx - 1] = config[idx - 1], config[idx]
    elif direction == "down" and idx < len(config) - 1:
        config[idx], config[idx + 1] = config[idx + 1], config[idx]
    else:
        return
    db.save_summary_config(user.id, config)
    await show_summary(query, user.id, chat_id, bot)


async def show_summary(query, user_id: int, chat_id: int, bot):
    from db import db

    config = db.get_summary_config(user_id)
    sort_mode = db.get_summary_sort_mode(user_id)

    # ── Build header with data ──
    now_str = datetime.now().strftime("%d.%m.%Y %H:%M")
    text = _pad(f"📊 *Сводка*\nОбновлено: {now_str}")

    has_data = False
    for section_key in config:
        line = await _fetch_section_data(user_id, section_key, db)
        if line:
            text += f"\n\n{line}"
            has_data = True

    if not has_data:
        text += "\n\n_Выбери разделы для отображения:_"

    # ── Build keyboard ──
    keyboard = []

    if sort_mode in ("up", "down"):
        arrow = "⬆️" if sort_mode == "up" else "⬇️"
        for section_key in config:
            emoji, label = SECTIONS_DICT.get(section_key, ("📌", section_key))
            keyboard.append([
                InlineKeyboardButton(
                    f"{arrow} {emoji} {label}",
                    callback_data=f"summary_move_{section_key}_{sort_mode}"
                )
            ])
    else:
        # Чекбоксы — каждый раздел отдельной строкой с названием
        for section_key, section_emoji, section_label in SECTIONS:
            is_selected = section_key in config
            cb = "☑️" if is_selected else "☐"
            keyboard.append([InlineKeyboardButton(
                f"{cb} {section_emoji}  {section_label}",
                callback_data=f"summary_toggle_{section_key}"
            )])

    # Bottom bar
    sort_lbl = {
        "": "🔀 Сортировка",
        "up": "⬆️ Сортировка",
        "down": "⬇️ Сортировка",
    }[sort_mode]
    keyboard.append([
        InlineKeyboardButton(sort_lbl, callback_data="summary_sort_cycle"),
        InlineKeyboardButton("🕐 Время", callback_data="widget_settings"),
    ])
    keyboard.append([btn_menu()])

    await query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
