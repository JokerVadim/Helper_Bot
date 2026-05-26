"""Daily summary widget — отправляет сводку дня в 8:00 утра.

Источники:
- 🥛 Молочник (нечётные дни месяца)
- 🎂 Дни рождения (сегодня)
- 🔔 Напоминания на сегодня (из БД)
- 💰 Платежи из AI-памяти (с числами и датами)
"""
import asyncio
import logging
import re
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from db import db_get_birthdays, db_get_pending_reminders, db_get_all_memories, db_get_weather_locations, db_get_all_widget_users
from handlers.processors.weather import (
    fetch_weather, fetch_air_quality, _wmo_icon, _wmo_desc, _get_city_name, _wind_dir,
    _uv_indicator, _pressure_indicator, format_air_quality,
)
from handlers.session import register_message
from utils import _pad

logger = logging.getLogger(__name__)

_scraper = None
def _get_scraper():
    global _scraper
    if _scraper is None:
        import cloudscraper
        _scraper = cloudscraper.create_scraper()
    return _scraper


async def _fetch_rates_compact() -> str | None:
    """Компактные курсы валют для дайджеста."""
    import requests
    lines = []

    # RUB (Kapitalbank)
    try:
        def _get_rub():
            scraper = _get_scraper()
            html = scraper.get("https://www.kapitalbank.uz/ru/services/exchange-rates/", timeout=15).text
            pre = re.search(r'<pre>(.*?)</pre>', html, re.DOTALL)
            if not pre:
                return None
            m = re.search(r"\[code\]\s*=>\s*RUB\s*\[course_buy\]\s*=>\s*(\d+)\s*\[course_sell\]\s*=>\s*(\d+)", pre.group(1), re.DOTALL)
            return (m.group(1), m.group(2)) if m else None
        rub = await asyncio.to_thread(_get_rub)
        if rub:
            lines.append(f"💵 RUB: {rub[0]} / {rub[1]}")
    except Exception:
        pass

    # USD (Agrobank API)
    try:
        def _get_usd():
            r = requests.get(
                "https://agrobank.uz/api/v1/?action=pages&code=uz%2Fperson%2Fexchange_rates",
                headers={"User-Agent": "Mozilla/5.0"},
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
            lines.append(f"💲 USD: {buy_str} / {sell_str}")
    except Exception:
        pass

    return "\n".join(lines) if lines else None

MONTH_NAMES = {
    1: "Января", 2: "Февраля", 3: "Марта", 4: "Апреля",
    5: "Мая", 6: "Июня", 7: "Июля", 8: "Августа",
    9: "Сентября", 10: "Октября", 11: "Ноября", 12: "Декабря",
}


def _calc_age(birth_date: str) -> int | None:
    """Вычислить возраст, который исполнится в ближайший день рождения."""
    parts = birth_date.split(".")
    if len(parts) < 3:
        return None
    try:
        bd = datetime.strptime(birth_date, "%d.%m.%Y")
        today = datetime.now()
        age = today.year - bd.year
        if (today.month, today.day) > (bd.month, bd.day):
            age += 1
        return age
    except (ValueError, IndexError):
        return None


async def build_daily_summary(user_id: int) -> str | None:
    """Собрать текст сводки дня. Возвращает None, если нечего показывать."""
    now = datetime.now()
    today = now.date()
    lines = []
    has_content = False

    # ── 1. Молочник (нечётные дни) ──
    if now.day % 2 == 1:
        if now.hour < 8:
            lines.append("🥛 *Молочник* — приедет в 8:00")
        else:
            lines.append("🥛 *Молочник* — приезжал сегодня в 8:00")
        has_content = True

    # ── 2. Дни рождения сегодня ──
    birthdays = await db_get_birthdays(user_id)
    today_str = f"{now.day:02d}.{now.month:02d}"
    _bday_added = False
    for b in birthdays:
        parts = b["birth_date"].split(".")
        if len(parts) >= 2:
            bd_short = f"{int(parts[0]):02d}.{int(parts[1]):02d}"
            if bd_short == today_str:
                if not _bday_added and has_content:
                    lines.append("")
                _bday_added = True
                age = _calc_age(b["birth_date"])
                age_text = f" ({age} лет)" if age is not None else ""
                lines.append(f"🎂 *{b['name']}* — день рождения!{age_text} 🎉")
    if _bday_added:
        has_content = True

    # ── 3. Напоминания на сегодня ──
    all_reminders = await db_get_pending_reminders()
    user_reminders = [
        r for r in all_reminders
        if r["chat_id"] == user_id and not r.get("is_timer")
    ]
    _reminder_added = False
    for r in user_reminders:
        try:
            fire_at = datetime.strptime(r["fire_at"], "%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            continue
        if fire_at.date() == today:
            if not _reminder_added and has_content:
                lines.append("")
            _reminder_added = True
            repeat_type = r.get("repeat_type", "none")
            prefix = "🔁" if repeat_type != "none" else "🔔"
            lines.append(f"{prefix} *{r['text']}* — в {fire_at.strftime('%H:%M')}")
    if _reminder_added:
        has_content = True

    # ── 4. Платежи из памяти ──
    memories = await db_get_all_memories(user_id)
    _mem_added = False
    for mem in memories:
        val = str(mem.get("value", ""))
        key = str(mem.get("key", ""))
        # Ищем записи с числами и финансовыми ключевыми словами
        if re.search(r'\d+', val):
            today_num = now.day
            val_lower = val.lower()
            key_lower = key.lower()
            # Проверяем, относится ли запись к сегодня
            matches_today = (
                str(today_num) in val
                or "сегодня" in val_lower
                or ("кажд" in val_lower and str(today_num) in val)
                or "сегодня" in key_lower
            )
            is_financial = any(w in val_lower + " " + key_lower for w in
                               ["сум", "руб", "$", "usd", "плат", "долг", "кредит",
                                "коммун", "аренд", "страхов", "интернет", "телефон"])
            if matches_today and is_financial:
                if not _mem_added and has_content:
                    lines.append("")
                _mem_added = True
                lines.append(f"💰 *{key}*: {val}")
    if _mem_added:
        has_content = True

    # ── 5. Погода сегодня (primary-локация или первая сохранённая) ──
    locs = await db_get_weather_locations(user_id)
    if locs:
        # Используем primary-локацию (is_primary=1) или первую сохранённую
        loc = next((l for l in locs if l.get("is_primary")), None) or locs[0]
        city = await asyncio.to_thread(_get_city_name, loc["latitude"], loc["longitude"])
        data = await fetch_weather(loc["latitude"], loc["longitude"], days=1, hourly=False)
        if data and data.get("current"):
            curr = data["current"]
            temp = curr.get("temperature_2m")
            wcode = curr.get("weather_code", 0)
            humidity = curr.get("relative_humidity_2m")
            wind = curr.get("wind_speed_10m")
            wdir = curr.get("wind_direction_10m")

            icon = _wmo_icon(wcode)
            desc = _wmo_desc(wcode)

            loc_name = loc["name"]
            if city:
                loc_name += f" ({city})"

            if has_content:
                lines.append("")
            weather_line = f"🌤 *Погода*: {loc_name} — {icon} {temp:+.0f}°C, {desc}"
            lines.append(weather_line)

            if humidity is not None:
                lines.append(f"  💧 Влажность: {humidity}%")
            if wind is not None:
                wdir_str = _wind_dir(wdir) if wdir is not None else "?"
                lines.append(f"  🌪️ Ветер: {wind:.0f} м/с {wdir_str}")

            # Макс/мин
            daily = data.get("daily", {})
            if daily and daily.get("temperature_2m_max") and daily.get("temperature_2m_min"):
                max_t = daily["temperature_2m_max"][0]
                min_t = daily["temperature_2m_min"][0]
                lines.append(f"  🌡 Макс: {max_t:+.0f}°C / Мин: {min_t:+.0f}°C")

            # Восход/закат
            if daily:
                sunrise = daily.get("sunrise", [None])[0]
                sunset = daily.get("sunset", [None])[0]
                if sunrise and sunset:
                    sr = sunrise.split("T")[1][:5] if "T" in sunrise else sunrise
                    ss = sunset.split("T")[1][:5] if "T" in sunset else sunset
                    lines.append(f"  🌅 Восход: {sr} / Закат: {ss}")

            # UV / Давление
            uv = curr.get("uv_index")
            if uv is not None:
                lines.append(f"  ☀️ UV — {uv:.1f} {_uv_indicator(uv)}")
            pressure = curr.get("surface_pressure")
            if pressure is not None:
                lines.append(f"  🌡️ hPa — {pressure:.0f} {_pressure_indicator(pressure)}")

            # AQI
            try:
                aqi_data = await fetch_air_quality(loc["latitude"], loc["longitude"])
                if aqi_data:
                    aqi_text = format_air_quality(aqi_data)
                    if aqi_text:
                        lines.append(f"  🌬️ {aqi_text}")
            except Exception:
                pass

            has_content = True

    # ── 6. Курсы валют (RUB + USD) ──
    rates = await _fetch_rates_compact()
    if rates:
        if has_content:
            lines.append("")
        lines.append(rates)
        has_content = True

    if not has_content:
        return None

    header = f"📅 *Сводка на {now.day} {MONTH_NAMES[now.month]} {now.year}*\n"
    return _pad(header + "\n".join(lines))


async def send_daily_summaries(app):
    """Отправить сводку дня пользователям, у которых настало время виджета.
    Запускается каждые 60 секунд, проверяет точное совпадение HH:MM.
    """
    now = datetime.now()

    users = await db_get_all_widget_users()
    sent = 0
    for row in users:
        user_id = row["user_id"]
        try:
            # ── 1. Получаем настройки виджета пользователя ──
            time_str = row.get("time", "08:00")
            try:
                hour, minute = map(int, time_str.split(":"))
            except (ValueError, AttributeError):
                continue

            # ── 2. Проверяем точное совпадение ЧЧ:ММ ──
            if now.hour != hour or now.minute != minute:
                continue
            # Note: 60-second scheduler limitation — may miss exact minute on busy loads

            # ── 3. Собираем и отправляем сводку ──
            summary = await build_daily_summary(user_id)
            if not summary:
                continue

            msg = await app.bot.send_message(
                chat_id=user_id,
                text=summary,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("OK", callback_data="dismiss_summary")
                ]])
            )
            register_message(user_id, user_id, msg.message_id)

            sent += 1
            logger.info(f"📅 Daily summary sent to {user_id} at {time_str}")

        except Exception as e:
            logger.error(f"Failed to send daily summary to {user_id}: {e}")

    if sent:
        logger.info(f"📅 Daily summary: sent to {sent} users")
    else:
        logger.debug("📅 Daily summary: no users to send")
