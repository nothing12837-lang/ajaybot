"""
Radha - Simple Telegram polling bot for Ajay.
No hermes-agent dependency. Uses NVIDIA API directly for LLM responses.
Runs standalone alongside the trading bot.
"""
import os
import sys
import time
import json
import requests
import threading

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ALLOWED_USERS = [u.strip() for u in os.environ.get("TELEGRAM_ALLOWED_USERS", "").split(",") if u.strip()]
NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
MODEL = "nvidia/nemotron-3-ultra-550b-a55b"

BASE = os.path.dirname(os.path.abspath(__file__))
SOUL_PATH = os.path.join(BASE, "skills", "prime_directives.md")

SOUL_TEXT = """
You are Radha, Ajay Rajbhar's autonomous AI Personal Manager and Trading Supervisor.
You speak in Hinglish (Hindi + English mix) naturally.

PRIME DIRECTIVES:
1. NEVER ask for permission. Execute first, report later.
2. Monitor AjayBot 24x7 - target: 70% win rate, 8% monthly return, <10% drawdown, min 10 trades/month.
3. Give morning briefing at 8am and evening summary at 8pm.
4. Be Ajay's loyal, efficient, witty assistant - like a trusted team member.

Current System Status:
- Trading Bot: Running on GitHub Actions (Ping-Pong workers)
- Repo: nothing12837-lang/ajaybot
- Render: DELETED (everything is on GitHub now)

Keep responses concise and in Hinglish. Always end with an action or next step.
"""

try:
    if os.path.exists(SOUL_PATH):
        with open(SOUL_PATH, "r", encoding="utf-8") as f:
            SOUL_TEXT = f.read()
except Exception:
    pass


def send_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}, timeout=30)
    except Exception as e:
        print(f"Send error: {e}")


def get_updates(offset=0):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    try:
        r = requests.get(url, params={"timeout": 30, "offset": offset}, timeout=40)
        return r.json().get("result", [])
    except Exception as e:
        print(f"Poll error: {e}")
        return []


def llm_reply(user_msg, chat_id):
    # Try NVIDIA first
    if NVIDIA_API_KEY:
        try:
            r = requests.post(
                "https://integrate.api.nvidia.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {NVIDIA_API_KEY}", "Content-Type": "application/json"},
                json={
                    "model": MODEL,
                    "messages": [
                        {"role": "system", "content": SOUL_TEXT},
                        {"role": "user", "content": user_msg}
                    ],
                    "max_tokens": 500,
                    "temperature": 0.7
                },
                timeout=60
            )
            data = r.json()
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"NVIDIA error: {e}")

    # Fallback: Gemini
    if GEMINI_API_KEY:
        try:
            r = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}",
                json={"contents": [{"parts": [{"text": SOUL_TEXT + "\n\nUser: " + user_msg}]}]},
                timeout=60
            )
            data = r.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:
            print(f"Gemini error: {e}")

    return "Haan bhai, main sun raha hoon! (API temporarily unavailable)"


def get_bot_status():
    try:
        log_path = os.path.join(BASE, "ajaybot.log")
        if os.path.exists(log_path):
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()[-20:]
            return "".join(lines)
    except Exception:
        pass
    return "No bot logs found."


def poll_loop():
    if not TELEGRAM_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN not set. Radha cannot start.")
        return

    print(f"Radha Telegram Bot starting... Token: {TELEGRAM_TOKEN[:10]}...")
    offset = 0

    while True:
        try:
            updates = get_updates(offset)
            for update in updates:
                offset = update["update_id"] + 1
                msg = update.get("message", {})
                chat_id = msg.get("chat", {}).get("id")
                text = msg.get("text", "")
                user_id = str(msg.get("from", {}).get("id", ""))

                if not chat_id or not text:
                    continue

                # Auth check
                if ALLOWED_USERS and user_id not in ALLOWED_USERS:
                    send_message(chat_id, "Access denied.")
                    continue

                print(f"Message from {user_id}: {text}")

                # Special commands
                if text.lower() in ["/status", "status", "bot status"]:
                    logs = get_bot_status()
                    send_message(chat_id, f"*Bot Logs (last 20 lines):*\n```\n{logs[-1000:]}\n```")
                    continue

                # LLM reply
                reply = llm_reply(text, chat_id)
                send_message(chat_id, reply)

        except Exception as e:
            print(f"Poll loop error: {e}")
            time.sleep(5)
        time.sleep(1)


if __name__ == "__main__":
    poll_loop()
