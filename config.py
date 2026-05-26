# config.py
import os
from dotenv import load_dotenv

load_dotenv()

# Admin / Access control
ADMIN_ID: int | None = None
_raw = os.getenv("ADMIN_ID")
if _raw:
    try:
        ADMIN_ID = int(_raw.strip())
    except ValueError:
        ADMIN_ID = None

# Allowed users (comma-separated IDs from .env)
ALLOWED_IDS: set[int] = set()
_raw = os.getenv("ALLOWED_IDS")
if _raw:
    for part in _raw.split(","):
        part = part.strip()
        if part:
            try:
                ALLOWED_IDS.add(int(part))
            except ValueError:
                pass

# Bot settings
MAX_REMINDERS_PER_CHAT = 50
MAX_CONTEXT_LENGTH = 4000
MAX_SEARCH_RESULTS = 8

# PIN protection
PIN_SESSION_MINUTES = 15
PIN_LOCKOUT_ATTEMPTS = 3  # кол-во неверных попыток до блокировки
PIN_LOCKOUT_SECONDS = 60  # длительность блокировки в секундах
# Auto-lock after 15 minutes of inactivity