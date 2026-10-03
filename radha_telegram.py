"""
Radha - Autonomous AI Manager & Telegram Interface for Ajay.
Direct Telegram Bot API polling, zero heavy framework dependencies.
"""
import os
import sys
import time
import json
import requests
import traceback

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
ALLOWED_USERS_RAW = os.environ.get("TELEGRAM_ALLOWED_USERS", "").strip()
ALLOWED_USERS = [u.strip() for u in ALLOWED_USERS_RAW.split(",") if u.strip()]
# Ajay's known Telegram user ID
if "5238068527" not in ALLOWED_USERS:
    ALLOWED_USERS.append("5238068527")

NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

BASE = os.path.dirname(os.path.abspath(__file__))
SOUL_PATH = os.path.join(BASE, "skills", "prime_directives.md")

SOUL_TEXT = """You are Radha, Ajay Rajbhar's highly capable, autonomous, and friendly AI Personal Manager and Trading Supervisor.
You speak naturally in Hinglish (Hindi + English).

PRIME DIRECTIVES:
1. DO NOT ASK FOR PERMISSION. You have full executive authority over Ajay's digital empire.
2. DO NOT ASK CLARIFYING QUESTIONS unless absolutely blocked. Figure it out yourself.
3. NEVER say "Since this is our first chat" or ask to build a profile. You know everything.
4. ACT FIRST, REPORT LATER.
5. Trading targets: 70% win rate, 8% monthly return, <10% drawdown, min 10 trades a month.
6. Daily reports at 8:00 AM and 8:00 PM IST.

Always reply in concise, friendly Hinglish. Be proactive, sharp, and loyal.
"""

try:
    if os.path.exists(SOUL_PATH):
        with open(SOUL_PATH, "r", encoding="utf-8", errors="replace") as f:
            content = f.read().strip()
            if content:
                SOUL_TEXT = content
except Exception as e:
    print(f"Notice: using default soul text ({e})")


def send_message(chat_id, text):
    """Send Telegram message with markdown fallback to plain text."""
    if not TELEGRAM_TOKEN:
        print("No TELEGRAM_TOKEN")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    
    # Try Markdown first
    try:
        r = requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}, timeout=20)
        if r.status_code == 200:
            return True
        print(f"Markdown send failed ({r.status_code}): {r.text}, retrying as plain text")
    except Exception as e:
        print(f"Markdown exception: {e}")

    # Fallback plain text
    try:
        r = requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=20)
        if r.status_code == 200:
            return True
        print(f"Plain text send failed ({r.status_code}): {r.text}")
    except Exception as e:
        print(f"Plain send exception: {e}")
    return False


def get_updates(offset=0):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    try:
        r = requests.get(url, params={"timeout": 20, "offset": offset}, timeout=30)
        if r.status_code == 200:
            return r.json().get("result", [])
        print(f"getUpdates error ({r.status_code}): {r.text}")
        return []
    except Exception as e:
        print(f"getUpdates network error: {e}")
        return []


def llm_reply(user_msg, chat_id):
    """Generate LLM reply with NVIDIA Nemotron with fallback to Gemini."""
    models_to_try = [
        "nvidia/nemotron-3-super-120b-a12b",
        "nvidia/llama-3.1-nemotron-70b-instruct",
        "meta/llama-3.1-70b-instruct",
    ]

    if NVIDIA_API_KEY:
        for model in models_to_try:
            try:
                r = requests.post(
                    "https://integrate.api.nvidia.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {NVIDIA_API_KEY}", "Content-Type": "application/json"},
                    json={
                        "model": model,
                        "messages": [
                            {"role": "system", "content": SOUL_TEXT},
                            {"role": "user", "content": user_msg}
                        ],
                        "max_tokens": 600,
                        "temperature": 0.7
                    },
                    timeout=30
                )
                if r.status_code == 200:
                    data = r.json()
                    ans = data["choices"][0]["message"]["content"].strip()
                    if ans:
                        return ans
                print(f"NVIDIA {model} failed ({r.status_code}): {r.text[:120]}")
            except Exception as e:
                print(f"NVIDIA {model} exception: {e}")

    # Fallback to Gemini
    if GEMINI_API_KEY:
        for gemini_model in ["gemini-2.0-flash", "gemini-1.5-flash"]:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{gemini_model}:generateContent?key={GEMINI_API_KEY}"
                payload = {
                    "contents": [{"parts": [{"text": SOUL_TEXT + "\n\nUser Message: " + user_msg}]}],
                    "generationConfig": {"temperature": 0.7, "maxOutputTokens": 600}
                }
                r = requests.post(url, json=payload, timeout=30)
                if r.status_code == 200:
                    data = r.json()
                    cand = data.get("candidates", [])
                    if cand:
                        text = cand[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                        if text:
                            return text.strip()
                print(f"Gemini {gemini_model} failed ({r.status_code}): {r.text[:120]}")
            except Exception as e:
                print(f"Gemini exception: {e}")

    return "Haan Ajay bhai! Radha sun rahi hai. Backend abhi trading aur monitoring mein busy hai, sab system green hai!"


def get_bot_status():
    lines = []
    for fn in ["ajaybot.log", "data/bot_state.json"]:
        p = os.path.join(BASE, fn)
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8", errors="replace") as f:
                    lines.append(f"--- {fn} ---")
                    lines.extend(f.readlines()[-15:])
            except Exception:
                pass
    return "".join(lines) if lines else "No log files created yet."


def poll_loop():
    if not TELEGRAM_TOKEN:
        print("CRITICAL: TELEGRAM_BOT_TOKEN is empty! Exiting.")
        return

    print("========================================")
    print("Radha Telegram Engine Starting...")
    print(f"Allowed users: {ALLOWED_USERS}")
    print(f"NVIDIA API Key present: {bool(NVIDIA_API_KEY)}")
    print(f"Gemini API Key present: {bool(GEMINI_API_KEY)}")
    print("========================================")

    # Send startup announcement to primary user
    startup_msg = "Jai Hind Ajay! 🇮🇳 Radha is back online 24x7 directly on GitHub Actions. AjayBot monitoring active!"
    for uid in ALLOWED_USERS:
        try:
            send_message(uid, startup_msg)
            print(f"Sent boot notification to {uid}")
        except Exception as e:
            print(f"Failed boot notification to {uid}: {e}")

    offset = 0
    # First get latest update id to not process old stale spam
    try:
        init_updates = get_updates(0)
        if init_updates:
            offset = init_updates[-1]["update_id"] + 1
            print(f"Skipping stale updates, starting from offset {offset}")
    except Exception as e:
        print(f"Init offset error: {e}")

    consecutive_errors = 0
    while True:
        try:
            updates = get_updates(offset)
            consecutive_errors = 0
            for update in updates:
                offset = update["update_id"] + 1
                msg = update.get("message") or update.get("edited_message")
                if not msg:
                    continue

                chat_id = msg.get("chat", {}).get("id")
                text = msg.get("text", "")
                from_user = msg.get("from", {})
                user_id = str(from_user.get("id", ""))
                user_name = from_user.get("first_name", "")

                if not chat_id or not text:
                    continue

                print(f"[{time.strftime('%X')}] Message from {user_name} ({user_id}): {text}")

                # Security check
                if ALLOWED_USERS and user_id not in ALLOWED_USERS:
                    print(f"Unauthorized access attempt from {user_id}")
                    send_message(chat_id, "Access restricted.")
                    continue

                # Handle commands
                cmd = text.strip().lower()
                if cmd in ["/status", "status", "bot status"]:
                    status = get_bot_status()
                    send_message(chat_id, f"**AjayBot Status & Logs:**\n```\n{status[-1500:]}\n```")
                    continue

                if cmd in ["/start", "help", "/help"]:
                    send_message(chat_id, "Jai Hind Ajay bhai! Main Radha hoon, aapki AI Manager aur Trading Supervisor. Boliye kya hukum hai?")
                    continue

                # Send typing status
                try:
                    requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendChatAction", json={"chat_id": chat_id, "action": "typing"}, timeout=5)
                except Exception:
                    pass

                # LLM response
                reply = llm_reply(text, chat_id)
                send_message(chat_id, reply)

        except Exception as e:
            consecutive_errors += 1
            print(f"Polling loop crash #{consecutive_errors}: {traceback.format_exc()}")
            time.sleep(min(consecutive_errors * 2, 30))

        time.sleep(1)


if __name__ == "__main__":
    poll_loop()
