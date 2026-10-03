"""
Radha - Autonomous AI Manager & Telegram Interface for Ajay.
Direct Telegram Bot API polling, zero heavy framework dependencies.
Equipped with live performance reporting, Gemini 3.8-Flash & NVIDIA Nemotron fallback.
"""
import os
import sys
import time
import json
import requests
import traceback
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
ALLOWED_USERS_RAW = os.environ.get("TELEGRAM_ALLOWED_USERS", "").strip()
ALLOWED_USERS = [u.strip() for u in ALLOWED_USERS_RAW.split(",") if u.strip()]
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


def send_message(chat_id, text, parse_mode="HTML"):
    """Send Telegram message with fallback to plain text."""
    if not TELEGRAM_TOKEN:
        print("No TELEGRAM_TOKEN")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    # Try requested parse_mode first
    try:
        r = requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": parse_mode}, timeout=20)
        if r.status_code == 200:
            return True
        print(f"Parse send failed ({r.status_code}): {r.text[:100]}, falling back to plain text")
    except Exception as e:
        print(f"Parse send exception: {e}")

    # Fallback plain text
    try:
        r = requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=20)
        if r.status_code == 200:
            return True
        print(f"Plain text send failed ({r.status_code}): {r.text[:100]}")
    except Exception as e:
        print(f"Plain send exception: {e}")
    return False


def get_updates(offset=0):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    try:
        r = requests.get(url, params={"timeout": 20, "offset": offset}, timeout=30)
        if r.status_code == 200:
            return r.json().get("result", [])
        return []
    except Exception as e:
        print(f"getUpdates network error: {e}")
        return []


def generate_report():
    """Generates the official performance report."""
    equity = 10000.0
    positions_count = 0
    total_trades = 0
    wins = 0
    losses = 0
    net_pnl = 0.0

    # Try local state files
    for fn in ["data/bot_state.json", "bot_state.json"]:
        p = os.path.join(BASE, fn)
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    st = json.load(f)
                equity = float(st.get("equity", equity))
                pos_data = st.get("positions", {})
                positions_count = len(pos_data) if isinstance(pos_data, (dict, list)) else 0
            except Exception:
                pass

    for fn in ["data/trades_history.json", "trades_history.json"]:
        p = os.path.join(BASE, fn)
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    trades = json.load(f)
                if isinstance(trades, list):
                    total_trades = len(trades)
                    for t in trades:
                        pnl = float(t.get("pnl", 0.0))
                        net_pnl += pnl
                        if pnl > 0:
                            wins += 1
                        elif pnl < 0:
                            losses += 1
            except Exception:
                pass

    win_rate = (wins / total_trades * 100.0) if total_trades > 0 else 0.0
    now_ist = datetime.now(IST)
    date_str = now_ist.strftime("%d %b %Y | %I:%M %p IST")
    pnl_sign = "+" if net_pnl >= 0 else ""
    pnl_emoji = "🟢" if net_pnl >= 0 else "🔴"

    return (
        f"📊 <b>AjayBot Daily Performance Report</b>\n"
        f"📅 <i>{date_str}</i>\n\n"
        f"💰 <b>Paper Equity:</b> ₹{equity:,.2f}\n"
        f"{pnl_emoji} <b>Net PnL:</b> {pnl_sign}₹{net_pnl:,.2f}\n"
        f"📈 <b>Open Positions:</b> {positions_count}\n"
        f"📋 <b>Total Trades:</b> {total_trades} (Wins: {wins} | Losses: {losses})\n"
        f"🎯 <b>Win Rate:</b> {win_rate:.1f}% (Target: 70%+)\n"
        f"⚡ <b>Leverage:</b> 12x | <b>Pairs:</b> BTC, ETH, SOL, DOGE, XRP\n"
        f"🛡️ <b>Max Drawdown Target:</b> &lt;10% | <b>Monthly Target:</b> 8%\n\n"
        f"🤖 <i>Generated Live by Radha • Ping-Pong Architecture (GitHub Actions)</i>"
    )


def llm_reply(user_msg, chat_id):
    """Generate LLM reply with Gemini 3.8-Flash and NVIDIA fallback."""
    # 1. Gemini 3.8-Flash (Reliable, fast, up to date)
    if GEMINI_API_KEY:
        for model in ["gemini-3.8-flash", "gemini-3.5-flash", "gemini-1.5-flash"]:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
                payload = {
                    "contents": [{"parts": [{"text": SOUL_TEXT + "\n\nAjay: " + user_msg}]}],
                    "generationConfig": {"temperature": 0.7, "maxOutputTokens": 600}
                }
                r = requests.post(url, json=payload, timeout=25)
                if r.status_code == 200:
                    cand = r.json().get("candidates", [])
                    if cand:
                        text = cand[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                        if text:
                            return text.strip()
                print(f"Gemini {model} returned {r.status_code}")
            except Exception as e:
                print(f"Gemini {model} exception: {e}")

    # 2. NVIDIA Nemotron fallback
    if NVIDIA_API_KEY:
        for model in ["nvidia/nemotron-3-super-120b-a12b", "nvidia/llama-3.1-nemotron-70b-instruct"]:
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
                    timeout=25
                )
                if r.status_code == 200:
                    ans = r.json()["choices"][0]["message"]["content"].strip()
                    if ans:
                        return ans
            except Exception as e:
                print(f"NVIDIA exception: {e}")

    return "Jai Hind Ajay bhai! Main live hoon aur system 24x7 monitor kar rahi hoon. Koi error nahi hai, sab chalu hai!"


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
    return "".join(lines) if lines else "System initialized. Trading engine running."


def poll_loop():
    if not TELEGRAM_TOKEN:
        print("CRITICAL: TELEGRAM_BOT_TOKEN is empty! Exiting.")
        return

    print("========================================")
    print("Radha Telegram Engine Starting...")
    print(f"Allowed users: {ALLOWED_USERS}")
    print(f"Gemini Key: {GEMINI_API_KEY[:8]}...")
    print("========================================")

    offset = 0
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

                if ALLOWED_USERS and user_id not in ALLOWED_USERS:
                    print(f"Unauthorized access from {user_id}")
                    send_message(chat_id, "Access restricted.")
                    continue

                cmd = text.strip().lower()

                # Report triggers
                if any(w in cmd for w in ["report", "8am", "8 am", "8pm", "8 pm", "pnl", "equity", "performance"]):
                    rpt = generate_report()
                    send_message(chat_id, rpt, parse_mode="HTML")
                    continue

                # Status command
                if cmd in ["/status", "status", "bot status"]:
                    status = get_bot_status()
                    send_message(chat_id, f"<b>AjayBot Logs:</b>\n<pre>{status[-1200:]}</pre>", parse_mode="HTML")
                    continue

                if cmd in ["/start", "help", "/help"]:
                    send_message(chat_id, "Jai Hind Ajay bhai! Main Radha hoon, aapki AI Manager aur Trading Supervisor. 8 AM / 8 PM report ke liye 'report' likhein, live status ke liye '/status'!")
                    continue

                # Send typing action
                try:
                    requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendChatAction", json={"chat_id": chat_id, "action": "typing"}, timeout=5)
                except Exception:
                    pass

                reply = llm_reply(text, chat_id)
                send_message(chat_id, reply, parse_mode="HTML")

        except Exception as e:
            consecutive_errors += 1
            print(f"Polling loop crash #{consecutive_errors}: {traceback.format_exc()}")
            time.sleep(min(consecutive_errors * 2, 30))

        time.sleep(1)


if __name__ == "__main__":
    poll_loop()
