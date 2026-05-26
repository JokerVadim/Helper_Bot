"""Send torrent download notification to Telegram."""
import os
import sys
import urllib.request
import json
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent

def load_env():
    """Load .env file."""
    env_file = SCRIPT_DIR / ".env"
    if not env_file.exists():
        print(f"ERROR: .env not found at {env_file}", file=sys.stderr)
        sys.exit(1)
    vars = {}
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, val = line.split("=", 1)
            vars[key.strip()] = val.strip().strip('"').strip("'")
    return vars

def read_temp_file(path):
    """Read temp file and return Unicode string."""
    path = Path(path)
    if not path.exists():
        return ""
    raw = path.read_bytes()
    # Remove trailing whitespace/null
    raw = raw.strip(b" \r\n\x00")
    if not raw:
        return ""
    # File is written by cmd.exe — encoding depends on chcp setting
    # Try UTF-8 first (chcp 65001), then CP866 (default OEM), then CP1251
    for enc in ("utf-8", "cp866", "cp1251"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")

def escape_html(text):
    """Escape HTML special characters for Telegram."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def main():
    temp = Path(os.environ.get("TEMP", os.environ.get("TMP", ".")))
    name_file = temp / "torrent_name.txt"
    files_file = temp / "torrent_files.txt"

    torrent_name = read_temp_file(name_file)
    torrent_content = read_temp_file(files_file)

    try:
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        try:
            sys.stderr = open(sys.__stdout__.fileno(), "w", encoding="utf-8", closefd=False)
        except Exception:
            pass
    try:
        print(f"Name: {torrent_name!r}")
        print(f"Content: {torrent_content!r}")
    except Exception:
        pass

    env = load_env()
    bot_token = env.get("BOT_TOKEN")
    chat_id = env.get("ADMIN_ID")

    if not bot_token or not chat_id:
        try:
            print("ERROR: BOT_TOKEN or ADMIN_ID not set", file=sys.stderr)
        except Exception:
            pass
        sys.exit(1)

    # Build message
    preview = ""
    if torrent_content:
        files = [f.strip() for f in torrent_content.split("\n") if f.strip()]
        if len(files) == 1 and files[0] == torrent_name:
            pass  # same as torrent name, no duplicate
        elif len(files) > 10:
            file_lines = "\n".join(escape_html(f) for f in files[:10])
            preview = f"\n{file_lines}\n...и ещё {len(files) - 10} файлов"
        else:
            preview = "\n" + "\n".join(escape_html(f) for f in files)

    text = f"✅ <b>Торрент скачан</b>\n\n📦 <b>{escape_html(torrent_name)}</b>{preview}"

    data = json.dumps({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "reply_markup": {"inline_keyboard": [[{"text": "OK", "callback_data": "dismiss_notify"}]]},
    }).encode("utf-8")

    req = urllib.request.Request(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read())
        try:
            print(f"OK: message sent (id={result['result']['message_id']})")
        except Exception:
            pass

if __name__ == "__main__":
    main()
