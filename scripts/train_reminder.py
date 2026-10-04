#!/usr/bin/env python3
"""Train Reminder Daily Check for Ajay (7:00 AM IST / 01:30 UTC).
Checks if today or tomorrow is Ajay's scheduled train journey and sends an alert
with PNR, coach, berth, and departure details.
"""
import os
import sys
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path

# IST Timezone (UTC + 5:30)
IST = timezone(timedelta(hours=5, minutes=30))

# Try loading from .env files
for env_candidate in [
    Path(__file__).parent.parent / ".env",
]:
    if env_candidate.exists():
        try:
            with open(env_candidate, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        k, v = line.split("=", 1)
                        if k not in os.environ and v:
                            os.environ[k] = v
        except Exception:
            pass

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_ALLOWED_USERS = os.environ.get("TELEGRAM_ALLOWED_USERS", "5238068527")
CHAT_ID = TELEGRAM_ALLOWED_USERS.split(",")[0].strip() if TELEGRAM_ALLOWED_USERS else "5238068527"

# Trip Details
JOURNEY_DATE = datetime(2026, 11, 4, 13, 30, tzinfo=IST)
PNR = "4764141969"
TRAIN = "12649 / SAMPARK KRANTI"
ROUTE = "YESVANTPUR JN (YPR) ➔ H NIZAMUDDIN (NZM)"
COACH = "B1"
BERTH = "18 (CNF, 3rd AC)"


def check_and_alert():
    now_ist = datetime.now(IST)
    today_date = now_ist.date()
    journey_date = JOURNEY_DATE.date()
    day_before = journey_date - timedelta(days=1)

    is_today = (today_date == journey_date)
    is_tomorrow = (today_date == day_before)

    if not is_today and not is_tomorrow:
        days_left = (journey_date - today_date).days
        print(f"Train reminder: {days_left} days left until journey on 04-Nov-2026. No alert needed today.")
        return True

    if not TELEGRAM_BOT_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN not configured.", file=sys.stderr)
        return False

    prefix = "🚨 <b>TODAY IS YOUR TRAVEL DAY!</b>" if is_today else "⚠️ <b>TRAIN TRAVEL TOMORROW!</b>"
    time_str = "1:30 PM Today" if is_today else "Tomorrow at 1:30 PM (04 Nov)"

    message = (
        f"{prefix}\n\n"
        f"🚆 <b>Train:</b> {TRAIN}\n"
        f"🎫 <b>PNR:</b> <code>{PNR}</code>\n"
        f"📍 <b>Route:</b> {ROUTE}\n"
        f"⏰ <b>Scheduled Departure:</b> {time_str}\n"
        f"💺 <b>Seat:</b> Coach {COACH}, Berth {BERTH}\n"
        f"👤 <b>Passenger:</b> AJAY KUMAR\n\n"
        f"💡 <i>Travel Checklist:</i>\n"
        f"• Original Govt ID card sath rakhna.\n"
        f"• Station par time se pehle reach karna.\n"
        f"• Mobile charge rakhna.\n\n"
        f"🤖 <i>AjayBot Travel Reminder • Safe travels!</i>"
    )

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
    }).encode("utf-8")

    try:
        req = urllib.request.Request(url, data=payload)
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status == 200:
                print("Train reminder alert dispatched to Telegram!")
                return True
    except Exception as e:
        print(f"Error sending Telegram alert: {e}", file=sys.stderr)
        return False


def main():
    success = check_and_alert()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
