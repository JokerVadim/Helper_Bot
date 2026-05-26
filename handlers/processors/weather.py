"""Weather module — Open-Meteo (бесплатно, без API ключа) + меню погоды.

Отдельный раздел "Погода" со своим UI как у остальных доменов:
- Кнопки сохранённых локаций → показать погоду
- [Добавить][Удалить][Редактировать][Меню]
"""
import asyncio
import logging
from datetime import datetime

import requests
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from db import (
    db_save_weather_location, db_get_weather_locations,
    db_delete_weather_location, db_rename_weather_location,
    db_update_weather_location_coords,
    db_set_primary_weather_location,
)
from keyboards import btn_menu, btn_cancel
from handlers.session import register_message, start_process, finish_process
from handlers.processors import register_message_handler, register_callback_handler
from utils import md, _pad

logger = logging.getLogger(__name__)

# Open-Meteo API
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"

# WMO weather codes → иконки и описание
WMO_CODES: dict[int, tuple[str, str]] = {
    0:  ("☀️",  "ясно"),
    1:  ("🌤",  "преимущественно ясно"),
    2:  ("⛅",  "переменная облачность"),
    3:  ("☁️",  "пасмурно"),
    5:  ("🌁",  "дымка"),
    10: ("🌫",  "туман"),
    20: ("🌦",  "морось"),
    45: ("🌫",  "туман"),
    48: ("🌫",  "изморозь"),
    51: ("🌦",  "морось"),
    53: ("🌦",  "морось"),
    55: ("🌦",  "морось"),
    56: ("🌦",  "ледяная морось"),
    57: ("🌦",  "ледяная морось"),
    61: ("🌧",  "небольшой дождь"),
    63: ("🌧",  "дождь"),
    65: ("🌧",  "сильный дождь"),
    66: ("🌧",  "ледяной дождь"),
    67: ("🌧",  "ледяной дождь"),
    71: ("🌨",  "небольшой снег"),
    73: ("🌨",  "снег"),
    75: ("🌨",  "сильный снег"),
    77: ("🌨",  "снежные зёрна"),
    80: ("🌦",  "ливень"),
    81: ("🌧",  "ливень"),
    82: ("🌧",  "сильный ливень"),
    85: ("🌨",  "снегопад"),
    86: ("🌨",  "сильный снегопад"),
    95: ("⛈",  "гроза"),
    96: ("⛈",  "гроза с градом"),
    99: ("⛈",  "гроза с градом"),
}

WEEKDAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]

MONTHS_RU = {
    1: "янв", 2: "фев", 3: "мар", 4: "апр", 5: "мая", 6: "июн",
    7: "июл", 8: "авг", 9: "сен", 10: "окт", 11: "ноя", 12: "дек",
}


def _wmo_icon(code: int) -> str:
    return WMO_CODES.get(code, ("🌡", "неизвестно"))[0]


def _wmo_desc(code: int) -> str:
    return WMO_CODES.get(code, ("🌡", "неизвестно"))[1]


def _wind_dir(deg: float) -> str:
    dirs = ["сев", "св", "вост", "юв", "южн", "юз", "зап", "сз"]
    idx = round(deg / 45) % 8
    return dirs[idx]


def _get_city_name(lat: float, lon: float) -> str | None:
    """Reverse geocoding через Nominatim."""
    url = "https://nominatim.openstreetmap.org/reverse"
    try:
        r = requests.get(
            url,
            params={"lat": lat, "lon": lon, "format": "json", "accept-language": "ru"},
            headers={"User-Agent": "TelegramBot/1.0"},
            timeout=5,
        )
        data = r.json()
        addr = data.get("address", {})
        return addr.get("city") or addr.get("town") or addr.get("village") or addr.get("state")
    except Exception as e:
        logger.warning(f"Reverse geocode error: {e}")
        return None


async def fetch_weather(lat: float, lon: float, days: int = 7, hourly: bool = False) -> dict | None:
    """Получить погоду от Open-Meteo.

    Args:
        lat, lon: координаты
        days: количество дней прогноза (1, 7, 16)
        hourly: запрашивать ли почасовые данные (для today)
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": [
            "temperature_2m",
            "relative_humidity_2m",
            "apparent_temperature",
            "weather_code",
            "wind_speed_10m",
            "wind_direction_10m",
            "surface_pressure",
            "uv_index",
        ],
        "daily": [
            "weather_code",
            "temperature_2m_max",
            "temperature_2m_min",
            "precipitation_sum",
            "sunrise",
            "sunset",
        ],
        "timezone": "Asia/Tashkent",
        "forecast_days": min(days, 16),
    }

    if hourly:
        params["hourly"] = [
            "temperature_2m",
            "weather_code",
            "precipitation_probability",
            "precipitation",
            "relative_humidity_2m",
            "cloud_cover",
        ]

    if days > 1:
        params["daily"] = [
            "weather_code",
            "temperature_2m_max",
            "temperature_2m_min",
            "precipitation_sum",
            "precipitation_probability_max",
            "uv_index_max",
        ]

    try:
        r = await asyncio.to_thread(
            lambda: requests.get(FORECAST_URL, params=params, timeout=10)
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.error(f"Open-Meteo error: {e}")
        return None


async def fetch_air_quality(lat: float, lon: float) -> dict | None:
    """Получить данные о качестве воздуха от Open-Meteo Air Quality API."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": ["european_aqi", "us_aqi", "pm10", "pm2_5", "carbon_monoxide", "nitrogen_dioxide", "sulphur_dioxide", "ozone"],
        "timezone": "Asia/Tashkent",
    }
    try:
        r = await asyncio.to_thread(
            lambda: requests.get(AIR_QUALITY_URL, params=params, timeout=10)
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.error(f"Air Quality API error: {e}")
        return None


def _uv_indicator(uv: float) -> str:
    """Цветной индикатор для UV индекса."""
    if uv <= 2:
        return "🟢"
    elif uv <= 5:
        return "🟡"
    elif uv <= 7:
        return "🟠"
    elif uv <= 10:
        return "🔴"
    else:
        return "🟣"


def _pressure_indicator(hpa: float) -> str:
    """Цветной индикатор для давления (гПа)."""
    if 1000 <= hpa <= 1020:
        return "🟢"
    elif hpa < 990:
        return "🔵"
    elif hpa >= 1025:
        return "🟠"
    else:
        return "🟢"


def _aqi_indicator(aqi: int) -> str:
    """Цветной индикатор для European AQI."""
    if aqi <= 50:
        return "🟢"
    elif aqi <= 100:
        return "🟡"
    elif aqi <= 150:
        return "🟠"
    elif aqi <= 200:
        return "🔴"
    elif aqi <= 300:
        return "🟣"
    else:
        return "⚫"


def format_air_quality(data: dict) -> str | None:
    """Форматировать данные о качестве воздуха (компактно)."""
    current = data.get("current")
    if not current:
        return None

    aqi = current.get("european_aqi")
    if aqi is None:
        return None

    indicator = _aqi_indicator(aqi)
    return f"AQI — {aqi} {indicator}"


def _format_day_label(date_str: str) -> str:
    """Форматировать дату в 'пн 22 июл'."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        wd = WEEKDAYS[dt.weekday()]
        day_num = dt.day
        month = MONTHS_RU[dt.month]
        return f"{wd} {day_num} {month}"
    except (ValueError, IndexError):
        return date_str


def _format_hour(time_str: str) -> str:
    """Из '2024-07-22T14:00' → '14:00'."""
    try:
        dt = datetime.fromisoformat(time_str)
        return dt.strftime("%H:%M")
    except (ValueError, TypeError):
        return time_str[-5:] if len(time_str) >= 5 else time_str


def format_weather_today(data: dict, location_name: str, city: str | None = None, air_quality: dict | None = None) -> str:
    """Форматировать сегодняшнюю погоду максимально подробно."""
    current = data.get("current", {})
    daily = data.get("daily", {})
    hourly = data.get("hourly", {})

    if not current:
        return "⚠️ Нет данных о погоде."

    temp = current.get("temperature_2m")
    feels = current.get("apparent_temperature")
    humidity = current.get("relative_humidity_2m")
    wcode = current.get("weather_code", 0)
    wind = current.get("wind_speed_10m")
    wdir = current.get("wind_direction_10m")
    pressure = current.get("surface_pressure")
    uv = current.get("uv_index")

    icon = _wmo_icon(wcode)
    desc = _wmo_desc(wcode)
    wdir_str = _wind_dir(wdir) if wdir is not None else "?"

    WEEKDAY_NAMES = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
    MONTH_GEN = {
        1: "января", 2: "февраля", 3: "марта", 4: "апреля", 5: "мая", 6: "июня",
        7: "июля", 8: "августа", 9: "сентября", 10: "октября", 11: "ноября", 12: "декабря",
    }

    lines = []

    # ── Шапка ──
    title = f"🌤 *Погода*: {location_name}"
    if city:
        title += f" ({city})"
    lines.append(title)

    # ── Дата ──
    if daily and daily.get("time"):
        try:
            dt = datetime.strptime(daily["time"][0], "%Y-%m-%d")
            wd = WEEKDAY_NAMES[dt.weekday()]
            date_str = f"📅 {wd.capitalize()}, {dt.day} {MONTH_GEN[dt.month]} {dt.year}"
            lines.append(date_str)
        except (ValueError, IndexError):
            pass

    lines.append("")

    # ── СЕЙЧАС ──
    lines.append("*━━━ СЕЙЧАС ━━━*")
    lines.append(f"{icon}  {temp:+.0f}°C  {desc}")
    lines.append(f"Ощущается: {feels:+.0f}°C")

    if humidity is not None:
        lines.append(f"💧 Влажность: {humidity}%")
    if wind is not None:
        lines.append(f"🌪️ Ветер: {wind:.0f} м/с, {wdir_str}")

    # UV / Воздух / Давление — каждый с новой строки
    if uv is not None:
        lines.append(f"☀️ UV — {uv:.1f} {_uv_indicator(uv)}")
    if air_quality:
        aqi_text = format_air_quality(air_quality)
        if aqi_text:
            lines.append(f"🌬️ {aqi_text}")
    if pressure is not None:
        lines.append(f"🌡️ hPa — {pressure:.0f} {_pressure_indicator(pressure)}")

    lines.append("")

    # ── ВОСХОД / ЗАКАТ ──
    if daily and daily.get("sunrise") and daily.get("sunset"):
        sunrise = _format_hour(daily["sunrise"][0]) if daily.get("sunrise") else "?"
        sunset = _format_hour(daily["sunset"][0]) if daily.get("sunset") else "?"
        lines.append("*━━━ ВОСХОД / ЗАКАТ ━━━*")
        lines.append(f"🌅 {sunrise}  🌇 {sunset}")

        # Световой день
        try:
            sr = datetime.strptime(daily["sunrise"][0], "%Y-%m-%dT%H:%M")
            ss = datetime.strptime(daily["sunset"][0], "%Y-%m-%dT%H:%M")
            delta = ss - sr
            hours = delta.seconds // 3600
            mins = (delta.seconds // 60) % 60
            lines.append(f"Световой день: {hours}ч {mins}мин")
        except (ValueError, IndexError):
            pass

        lines.append("")

    # ── ПОГОДА ПО ЧАСАМ ──
    if hourly and hourly.get("time"):
        lines.append("*━━━ ПОГОДА ПО ЧАСАМ ━━━*")

        times = hourly["time"]
        temps = hourly.get("temperature_2m", [])
        codes = hourly.get("weather_code", [])
        precip_prob = hourly.get("precipitation_probability", [])
        precipitation = hourly.get("precipitation", [])

        # Показываем каждый час: 00, 01, 02 … 23
        now_hour = datetime.now().hour
        for i in range(len(times)):
            try:
                hour_dt = datetime.fromisoformat(times[i])
            except (ValueError, TypeError):
                continue

            h = hour_dt.hour

            h_temp = temps[i] if i < len(temps) else None
            h_code = codes[i] if i < len(codes) else 0
            h_prob = precip_prob[i] if i < len(precip_prob) else 0
            h_precip = precipitation[i] if i < len(precipitation) else 0

            h_icon = _wmo_icon(h_code)
            h_time = hour_dt.strftime("%H:%M")
            temp_str = f"{h_temp:+}°C" if h_temp is not None else "?"

            line = f"{h_icon}  {h_time}  {temp_str}"
            if h_prob and h_prob > 5:
                line += f"  🌧 {int(h_prob)}%"
            if h_precip and h_precip > 0:
                line += f"  ({h_precip:.1f} мм)"

            if h == now_hour:
                line = f"*{line}*"
            lines.append(line)

        lines.append("")

    # ── ИТОГИ ДНЯ ──
    if daily and daily.get("temperature_2m_max") and daily.get("temperature_2m_min"):
        lines.append("*━━━ ИТОГИ ДНЯ ━━━*")

        max_t = daily["temperature_2m_max"][0]
        min_t = daily["temperature_2m_min"][0]
        lines.append(f"🌡  Макс: {max_t:+}°C  /  Мин: {min_t:+}°C")

        # Влажность: диапазон из почасовых
        if hourly and hourly.get("relative_humidity_2m"):
            hums = [h for h in hourly["relative_humidity_2m"] if h is not None]
            if hums:
                lines.append(f"💧  Влажность: {min(hums)}–{max(hums)}%")

        # Осадки: сумма + вероятность
        precip_sum = daily.get("precipitation_sum", [0])[0] if daily.get("precipitation_sum") else 0
        prob_max = 0
        if hourly and hourly.get("precipitation_probability"):
            probs = [p for p in hourly["precipitation_probability"] if p is not None]
            if probs:
                prob_max = max(probs)

        precip_parts = []
        if precip_sum and precip_sum > 0:
            precip_parts.append(f"{precip_sum:.1f} мм")
        if prob_max and prob_max > 5:
            precip_parts.append(f"вер. {int(prob_max)}%")
        if precip_parts:
            lines.append(f"🌧  Осадки: {' / '.join(precip_parts)}")
        else:
            lines.append("🌧  Осадки: 0 мм")

        # Облачность: средняя из почасовых
        if hourly and hourly.get("cloud_cover"):
            clouds = [c for c in hourly["cloud_cover"] if c is not None]
            if clouds:
                avg_cloud = sum(clouds) / len(clouds)
                lines.append(f"☁️  Облачность: {avg_cloud:.0f}%")

    return "\n".join(lines)


def format_weather_period(data: dict, location_name: str, city: str | None = None, days: int = 7) -> str:
    """Форматировать прогноз на N дней (неделя или месяц) — день/ночь."""
    daily = data.get("daily", {})
    hourly = data.get("hourly", {})

    if not daily or not daily.get("time"):
        return "⚠️ Нет данных прогноза."

    period_label = {
        7: "неделю",
        16: "16 дней",
    }.get(days, f"{days} дней")

    title = f"🌤 *Погода*: {location_name}"
    if city:
        title += f" ({city})"

    lines = [title, ""]
    lines.append(f"📅 *Прогноз на {period_label}:*")
    lines.append("")

    times = daily["time"]
    codes = daily.get("weather_code", [])
    highs = daily.get("temperature_2m_max", [])
    lows = daily.get("temperature_2m_min", [])
    precip = daily.get("precipitation_sum", [])
    precip_max = daily.get("precipitation_probability_max", [])

    # Группируем почасовые данные по дню: дневные часы (06–17) и ночные (18–05)
    hou_day: dict[str, list[int]] = {}
    hou_night: dict[str, list[int]] = {}
    if hourly and hourly.get("time"):
        for i in range(len(hourly["time"])):
            try:
                dt = datetime.fromisoformat(hourly["time"][i])
            except (ValueError, TypeError):
                continue
            key = dt.strftime("%Y-%m-%d")
            wc = hourly.get("weather_code", [])[i] if i < len(hourly.get("weather_code", [])) else 0
            if 6 <= dt.hour <= 17:
                hou_day.setdefault(key, []).append(wc)
            else:
                hou_night.setdefault(key, []).append(wc)

    today_str = datetime.now().strftime("%Y-%m-%d")
    for i in range(len(times)):
        date = times[i]
        day_label = "Сегодня" if date == today_str else _format_day_label(date)
        lines.append(f"*━━━ {day_label} ━━━*")

        d_code = codes[i] if i < len(codes) else 0
        max_t = highs[i] if i < len(highs) else None
        min_t = lows[i] if i < len(lows) else None
        precip_sum = precip[i] if i < len(precip) else 0
        precip_prob = precip_max[i] if i < len(precip_max) else 0

        # Дневная погода (06–17) — из почасовых, fallback на daily
        day_codes = hou_day.get(date, [])
        if day_codes:
            day_code = max(set(day_codes), key=lambda c: day_codes.count(c))
        else:
            day_code = d_code

        # Ночная погода (18–05) — из почасовых, fallback на daily
        night_codes = hou_night.get(date, [])
        if night_codes:
            night_code = max(set(night_codes), key=lambda c: night_codes.count(c))
        else:
            night_code = d_code

        # День
        day_icon = _wmo_icon(day_code)
        day_desc = _wmo_desc(day_code)
        day_temp = f"{max_t:+.0f}°C" if max_t is not None else "?"
        lines.append(f"{day_icon}  День: {day_temp}  {day_desc}")

        # Ночь
        night_icon = "🌙" if night_code == 0 else _wmo_icon(night_code)
        night_desc = "ясно" if night_code == 0 else _wmo_desc(night_code)
        night_temp = f"{min_t:+.0f}°C" if min_t is not None else "?"
        lines.append(f"{night_icon}  Ночь: {night_temp}  {night_desc}")

        # Осадки
        precip_parts = []
        if precip_sum and precip_sum > 0:
            precip_parts.append(f"{precip_sum:.1f} мм")
        if precip_prob and precip_prob > 5:
            precip_parts.append(f"{int(precip_prob)}%")
        if precip_parts:
            lines.append(f"💧  {' / '.join(precip_parts)}")
        else:
            lines.append("💧  0 мм")

        # UV индекс
        uv_max = daily.get("uv_index_max", [None])[i] if daily.get("uv_index_max") else None
        if uv_max is not None:
            lines.append(f"☀️  UV {uv_max:.1f} {_uv_indicator(uv_max)}")

        lines.append("")  # отступ между днями

    return "\n".join(lines).rstrip()


def format_weather(data: dict, location_name: str, city: str | None = None) -> str:
    """Форматировать данные погоды в текст сообщения (для обратной совместимости с locweather_)."""
    return format_weather_today(data, location_name, city)


async def get_weather_text(lat: float, lon: float, loc_name: str) -> str:
    """Получить и отформатировать погоду для локации (для обратной совместимости с locweather_)."""
    city = await asyncio.to_thread(_get_city_name, lat, lon)
    data = await fetch_weather(lat, lon, days=1, hourly=True)
    if not data:
        return f"⚠️ Не удалось получить погоду для *{md(loc_name)}*."
    air_quality = await fetch_air_quality(lat, lon)
    return format_weather_today(data, loc_name, city, air_quality)


async def _build_weather_view(loc_id: int, user_id: int, period: str) -> tuple[str, list]:
    """Построить текст погоды и клавиатуру для указанного периода."""
    locs = await db_get_weather_locations(user_id)
    loc = next((l for l in locs if l["id"] == loc_id), None)
    if not loc:
        return "❌ Локация не найдена.", [[btn_menu()]]

    city = await asyncio.to_thread(_get_city_name, loc["latitude"], loc["longitude"])

    if period == "today":
        data = await fetch_weather(loc["latitude"], loc["longitude"], days=1, hourly=True)
        if not data:
            return f"⚠️ Не удалось получить погоду для *{loc['name']}*.", [[btn_menu()]]
        air_quality = await fetch_air_quality(loc["latitude"], loc["longitude"])
        text = format_weather_today(data, loc["name"], city, air_quality)
    elif period == "week":
        data = await fetch_weather(loc["latitude"], loc["longitude"], days=7, hourly=True)
        if not data:
            return f"⚠️ Не удалось получить погоду для *{loc['name']}*.", [[btn_menu()]]
        text = format_weather_period(data, loc["name"], city, days=7)
    else:
        return "⚠️ Неизвестный период.", [[btn_menu()]]

    # Строим клавиатуру: слева выбор времени, справа OK — всё в одной строке
    keyboard = []
    row = []
    if period != "today":
        row.append(InlineKeyboardButton("📅 Сегодня", callback_data=f"weather_today_{loc_id}"))
    if period != "week":
        row.append(InlineKeyboardButton("📅 Неделя", callback_data=f"weather_week_{loc_id}"))
    row.append(InlineKeyboardButton("OK", callback_data="weather_ok"))
    keyboard.append(row)

    return text, keyboard

# ═══════════════════════════════════════════════════════════════════════════════
# UI: Показать меню погоды
# ═══════════════════════════════════════════════════════════════════════════════

async def _show_weather_menu(query, custom_text: str = None, bot=None, user_id: int = None):
    """Показать меню погоды со списком сохранённых локаций."""
    uid = user_id or query.from_user.id
    locs = await db_get_weather_locations(uid)
    keyboard = []

    text = _pad("🌤 *Погода*")
    if custom_text:
        text = custom_text

    if not locs:
        text = _pad("🌤 *Погода*\n\nПока нет сохранённых локаций для погоды.\nНажми ✚ Добавить, чтобы добавить.")
    else:
        for loc in locs:
            label = f"⭐ {loc['name']}" if loc.get("is_primary") else loc['name']
            keyboard.append([InlineKeyboardButton(label, callback_data=f"viewweather_{loc['id']}")])

    keyboard.append([
        InlineKeyboardButton("✚ Добавить", callback_data="add_weather_location"),
        InlineKeyboardButton("🗑 Удалить", callback_data="weather_mode_delete"),
    ])
    keyboard.append([
        InlineKeyboardButton("✏️ Редактировать", callback_data="weather_mode_edit"),
        btn_menu(),
    ])

    if bot and user_id:
        msg = await bot.send_message(chat_id=user_id, text=text, parse_mode="Markdown",
                                     reply_markup=InlineKeyboardMarkup(keyboard))
        register_message(user_id, user_id, msg.message_id)
    elif query:
        await query.edit_message_text(text, parse_mode="Markdown",
                                      reply_markup=InlineKeyboardMarkup(keyboard))


# ═══════════════════════════════════════════════════════════════════════════════
# Callback Handlers
# ═══════════════════════════════════════════════════════════════════════════════

@register_callback_handler("open_weather_menu")
async def cb_open_weather_menu(query, context, data, user, chat_id, bot):
    """Открыть меню погоды."""
    await _show_weather_menu(query)


@register_callback_handler("add_weather_location")
async def cb_add_weather_location(query, context, data, user, chat_id, bot):
    """Начать добавление локации для погоды."""
    start_process(user.id, chat_id, "weather_location", {"step": "waiting_name"}, query.message.message_id)
    await query.edit_message_text(
        _pad("🌤 *Добавить локацию для погоды*\n\nВведи название (например: Дом, Пляж, Дача):"),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
    )


@register_callback_handler("viewweather_")
async def cb_view_weather(query, context, data, user, chat_id, bot):
    """Показать погоду для конкретной локации — сначала today с кнопками [Неделя] [Месяц] [OK]."""
    loc_id = int(data.split("_")[1])
    locs = await db_get_weather_locations(user.id)
    loc = next((l for l in locs if l["id"] == loc_id), None)
    if not loc:
        await query.edit_message_text(_pad("❌ Локация не найдена."))
        return

    await query.edit_message_text(_pad("🌤 Получаю погоду..."))
    text, keyboard = await _build_weather_view(loc_id, user.id, "today")
    await query.edit_message_text(
        _pad(text),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


@register_callback_handler("weather_today_")
async def cb_weather_today(query, context, data, user, chat_id, bot):
    """Показать сегодняшнюю погоду для локации."""
    loc_id = int(data.split("_")[2])
    await query.edit_message_text(_pad("🌤 Получаю погоду..."))
    text, keyboard = await _build_weather_view(loc_id, user.id, "today")
    await query.edit_message_text(
        _pad(text),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


@register_callback_handler("weather_week_")
async def cb_weather_week(query, context, data, user, chat_id, bot):
    """Показать прогноз на неделю для локации."""
    loc_id = int(data.split("_")[2])
    await query.edit_message_text(_pad("🌤 Получаю прогноз на неделю..."))
    text, keyboard = await _build_weather_view(loc_id, user.id, "week")
    await query.edit_message_text(
        _pad(text),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


@register_callback_handler("weather_ok")
async def cb_weather_ok(query, context, data, user, chat_id, bot):
    """Закрыть погоду и показать меню погоды."""
    try:
        await bot.delete_message(chat_id=chat_id, message_id=query.message.message_id)
    except Exception as e:
        logger.debug(f"Не удалось удалить weather-сообщение: {e}")
    await _show_weather_menu(query=None, bot=bot, user_id=user.id)


# ─── Удаление ────────────────────────────────────────────────────────────────

@register_callback_handler("weather_mode_delete")
async def cb_weather_mode_delete(query, context, data, user, chat_id, bot):
    """Показать локации в режиме удаления."""
    locs = await db_get_weather_locations(user.id)
    if not locs:
        await query.edit_message_text(
            _pad("🌤 *Удаление локаций*\n\nНет сохранённых локаций."),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[btn_menu()]])
        )
        return

    keyboard = []
    for loc in locs:
        keyboard.append([InlineKeyboardButton(f"🗑 {loc['name']}", callback_data=f"delweather_{loc['id']}")])

    keyboard.append([
        InlineKeyboardButton("✚ Добавить", callback_data="add_weather_location"),
        InlineKeyboardButton("✅ Готово", callback_data="open_weather_menu"),
    ])
    keyboard.append([btn_menu()])

    await query.edit_message_text(
        _pad("🗑 *Выбери локацию для удаления:*"),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


@register_callback_handler("delweather_")
async def cb_del_weather(query, context, data, user, chat_id, bot):
    """Подтверждение удаления локации."""
    loc_id = int(data.split("_")[1])
    locs = await db_get_weather_locations(user.id)
    loc = next((l for l in locs if l["id"] == loc_id), None)

    if not loc:
        await query.answer("❌ Локация не найдена", show_alert=True)
        return

    await query.edit_message_text(
        _pad(f"🗑 Удалить локацию *{md(loc['name'])}*?"),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Да, удалить", callback_data=f"confirmdelweather_{loc_id}")],
            [InlineKeyboardButton("◀️ Назад", callback_data="weather_mode_delete"), btn_menu()],
        ])
    )


@register_callback_handler("confirmdelweather_")
async def cb_confirm_del_weather(query, context, data, user, chat_id, bot):
    """Подтвердить удаление локации."""
    loc_id = int(data.split("_")[1])
    await db_delete_weather_location(user.id, loc_id)
    await _show_weather_menu(query, custom_text=_pad("✅ Локация удалена."))


# ─── Редактирование ──────────────────────────────────────────────────────────

async def _show_weather_edit_menu(query, user_id: int, chat_id: int, custom_text: str = None):
    """Показать меню редактирования: ☆/⭐ для выбора основной + доп. действия."""
    locs = await db_get_weather_locations(user_id)
    keyboard = []

    text = _pad("⭐ *Нажми на ☆ чтобы сделать основной*")
    if custom_text:
        text = custom_text

    for loc in locs:
        if loc.get("is_primary"):
            label = f"⭐ {loc['name']}"
        else:
            label = f"☆ {loc['name']}"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"edit_setprimary_{loc['id']}")])

    keyboard.append([
        InlineKeyboardButton("✏️ Название", callback_data="weather_mode_edit_name"),
        InlineKeyboardButton("📍 Координаты", callback_data="weather_mode_edit_coords"),
    ])
    keyboard.append([
        InlineKeyboardButton("✅ Готово", callback_data="open_weather_menu"),
        btn_menu(),
    ])

    await query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


@register_callback_handler("weather_mode_edit")
async def cb_weather_mode_edit(query, context, data, user, chat_id, bot):
    """Показать меню редактирования локаций (выбор основной + доп. действия)."""
    locs = await db_get_weather_locations(user.id)
    if not locs:
        await query.edit_message_text(
            _pad("🌤 *Редактирование*\n\nНет сохранённых локаций."),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[btn_menu()]])
        )
        return

    await _show_weather_edit_menu(query, user.id, chat_id)


@register_callback_handler("edit_setprimary_")
async def cb_edit_set_primary(query, context, data, user, chat_id, bot):
    """Сделать локацию основной из меню редактирования."""
    loc_id = int(data.split("_")[2])
    await db_set_primary_weather_location(user.id, loc_id)
    await _show_weather_edit_menu(
        query, user.id, chat_id,
        custom_text=_pad("⭐ *Основная локация изменена!*\n\nНажми на ☆ чтобы сделать основной:")
    )


@register_callback_handler("weather_mode_edit_name")
async def cb_weather_mode_edit_name(query, context, data, user, chat_id, bot):
    """Показать локации для выбора переименования."""
    locs = await db_get_weather_locations(user.id)
    if not locs:
        await query.edit_message_text(_pad("🌤 Нет локаций."), reply_markup=InlineKeyboardMarkup([[btn_menu()]]))
        return
    keyboard = []
    for loc in locs:
        keyboard.append([InlineKeyboardButton(f"✏️ {loc['name']}", callback_data=f"editweathername_{loc['id']}")])
    keyboard.append([
        InlineKeyboardButton("◀️ Назад", callback_data="weather_mode_edit"),
        btn_menu(),
    ])
    await query.edit_message_text(
        _pad("✏️ *Выбери локацию для переименования:*"),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


@register_callback_handler("weather_mode_edit_coords")
async def cb_weather_mode_edit_coords(query, context, data, user, chat_id, bot):
    """Показать локации для выбора изменения координат."""
    locs = await db_get_weather_locations(user.id)
    if not locs:
        await query.edit_message_text(_pad("🌤 Нет локаций."), reply_markup=InlineKeyboardMarkup([[btn_menu()]]))
        return
    keyboard = []
    for loc in locs:
        keyboard.append([InlineKeyboardButton(f"📍 {loc['name']}", callback_data=f"editweathercoords_{loc['id']}")])
    keyboard.append([
        InlineKeyboardButton("◀️ Назад", callback_data="weather_mode_edit"),
        btn_menu(),
    ])
    await query.edit_message_text(
        _pad("📍 *Выбери локацию для изменения координат:*"),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


@register_callback_handler("editweathername_")
async def cb_edit_weather_name(query, context, data, user, chat_id, bot):
    """Изменить название локации."""
    loc_id = int(data.split("_")[1])
    locs = await db_get_weather_locations(user.id)
    loc = next((l for l in locs if l["id"] == loc_id), None)

    if not loc:
        await query.answer("❌ Локация не найдена", show_alert=True)
        return

    start_process(user.id, chat_id, "weather_edit_name", {
        "step": "waiting_name", "loc_id": loc_id, "old_name": loc["name"]
    }, query.message.message_id)
    await query.edit_message_text(
        _pad(f"✏️ Введи новое название для `{md(loc['name'])}`:"),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
    )


@register_callback_handler("editweathercoords_")
async def cb_edit_weather_coords(query, context, data, user, chat_id, bot):
    """Изменить координаты локации."""
    loc_id = int(data.split("_")[1])
    locs = await db_get_weather_locations(user.id)
    loc = next((l for l in locs if l["id"] == loc_id), None)

    if not loc:
        await query.answer("❌ Локация не найдена", show_alert=True)
        return

    start_process(user.id, chat_id, "weather_edit_coords", {
        "step": "waiting_coords", "loc_id": loc_id, "name": loc["name"]
    }, query.message.message_id)
    await query.edit_message_text(
        _pad(f"📍 Отправь новую геолокацию для `{md(loc['name'])}` (нажми скрепку → геолокация):"),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
    )



# ═══════════════════════════════════════════════════════════════════════════════
# Message Handlers
# ═══════════════════════════════════════════════════════════════════════════════

@register_message_handler("weather_location")
async def handle_weather_location_add(update, context, proc, state):
    """Обработка добавления погодной локации: имя → геолокация."""
    user = update.effective_user
    chat_id = update.effective_chat.id
    message = update.message or update.effective_message
    text = message.text.strip() if message.text else ""
    bot = context.bot
    register_message(user.id, chat_id, message.message_id)

    step = state.get("step")

    if step == "waiting_name":
        if not text:
            reply = await message.reply_text(
                _pad("❌ Название не может быть пустым. Введи название:"),
                reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
            )
            register_message(user.id, chat_id, reply.message_id)
            return

        state["name"] = text
        state["step"] = "waiting_location"

        reply = await message.reply_text(
            _pad(f"🌤 Название: *{md(text)}*\n\nТеперь отправь локацию (нажми скрепку → геолокация):"),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        register_message(user.id, chat_id, reply.message_id)

    elif step == "waiting_location":
        if not message.location:
            reply = await message.reply_text(
                _pad("❌ Локация не получена. Нажми скрепку → геолокация."),
                reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
            )
            register_message(user.id, chat_id, reply.message_id)
            return

        name = state.get("name", "Локация")
        lat = message.location.latitude
        lon = message.location.longitude

        loc_id = await db_save_weather_location(user.id, name, lat, lon)
        await finish_process(bot, user.id, show_menu=False)

        # Спрашиваем, сделать ли основной
        msg = await bot.send_message(
            chat_id=user.id,
            text=_pad(f"✅ *{md(name)}* добавлена!\n\nСделать её основной для сводки погоды?"),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("⭐ Да", callback_data=f"weather_setprimary_{loc_id}"),
                    InlineKeyboardButton("❌ Нет", callback_data="open_weather_menu"),
                ]
            ])
        )
        register_message(user.id, user.id, msg.message_id)


@register_callback_handler("weather_setprimary_")
async def cb_weather_set_primary(query, context, data, user, chat_id, bot):
    """Сделать локацию основной для сводки погоды."""
    loc_id = int(data.split("_")[2])
    await db_set_primary_weather_location(user.id, loc_id)
    await _show_weather_menu(
        query, custom_text=_pad("⭐ Локация отмечена как основная!"),
    )


@register_message_handler("weather_edit_name")
async def handle_weather_edit_name(update, context, proc, state):
    """Обработка редактирования названия погодной локации."""
    user = update.effective_user
    chat_id = update.effective_chat.id
    message = update.message or update.effective_message
    text = message.text.strip() if message.text else ""
    bot = context.bot
    register_message(user.id, chat_id, message.message_id)

    loc_id = state.get("loc_id")
    old_name = state.get("old_name", "")

    if not text:
        reply = await message.reply_text(
            _pad("✏️ Название не может быть пустым. Введи новое название:"),
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        register_message(user.id, chat_id, reply.message_id)
        return

    await db_rename_weather_location(user.id, loc_id, text)
    await finish_process(bot, user.id, show_menu=False)

    await _show_weather_menu(
        query=None, bot=bot, user_id=user.id,
        custom_text=_pad(f"✅ Название изменено: *{md(old_name)}* → *{md(text)}*"),
    )


@register_message_handler("weather_edit_coords")
async def handle_weather_edit_coords(update, context, proc, state):
    """Обработка редактирования координат погодной локации."""
    user = update.effective_user
    chat_id = update.effective_chat.id
    message = update.message or update.effective_message
    bot = context.bot
    register_message(user.id, chat_id, message.message_id)

    loc_id = state.get("loc_id")
    name = state.get("name", "")

    if not message.location:
        reply = await message.reply_text(
            _pad("📍 Отправь новую геолокацию (нажми скрепку → геолокация):"),
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        register_message(user.id, chat_id, reply.message_id)
        return

    lat = message.location.latitude
    lon = message.location.longitude
    await db_update_weather_location_coords(user.id, loc_id, lat, lon)
    await finish_process(bot, user.id, show_menu=False)

    await _show_weather_menu(
        query=None, bot=bot, user_id=user.id,
        custom_text=_pad(f"✅ Координаты для *{md(name)}* обновлены!"),
    )
