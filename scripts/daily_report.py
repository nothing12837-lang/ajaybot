#!/usr/bin/env python3
"""Daily Trading Performance Report for Ajay (10:30 AM IST / 05:00 UTC).
Fetches latest trading state from Hugging Face dataset rareember/ajaybot-state,
computes key metrics (equity, open positions, win rate, net PnL), and dispatches
a clean HTML digest directly to Ajay's Telegram.
"""
import os
import sys
import json
import tempfile
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path

# IST Timezone (UTC + 5:30)
IST = timezone(timedelta(hours=5, minutes=30))

# Try loading from .env files if environment variables are missing
for env_candidate in [
    Path("/opt/render/project/src/hermes-home/.env"),
    Path(__file__).parent.parent / "hermes-home" / ".env",
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

HF_TOKEN = os.environ.get("HF_TOKEN")
HF_REPO = os.environ.get("HF_STATE_REPO", "rareember/ajaybot-state")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_ALLOWED_USERS = os.environ.get("TELEGRAM_ALLOWED_USERS", "5238068527")
CHAT_ID = TELEGRAM_ALLOWED_USERS.split(",")[0].strip() if TELEGRAM_ALLOWED_USERS else "5238068527"


def fetch_performance():
    equity = 10000.0
    positions_count = 0
    total_trades = 0
    wins = 0
    losses = 0
    net_pnl = 0.0

    state_loaded = False
    try:
        from huggingface_hub import snapshot_download
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            snapshot_download(
                repo_id=HF_REPO,
                repo_type="dataset",
                token=HF_TOKEN,
                local_dir=tmp,
            )
            state_file = tmp / "bot_state.json"
            trades_file = tmp / "trades_history.json"

            if state_file.exists():
                with open(state_file, "r", encoding="utf-8") as f:
                    state = json.load(f)
                equity = float(state.get("equity", 10000.0))
                pos_data = state.get("positions", {})
                positions_count = len(pos_data) if isinstance(pos_data, (dict, list)) else 0
                state_loaded = True

            if trades_file.exists():
                with open(trades_file, "r", encoding="utf-8") as f:
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
                    state_loaded = True
    except Exception as e:
        print(f"Warning: Failed to fetch state from HF: {e}", file=sys.stderr)

    # Local fallback if HF fetch was empty
    if not state_loaded:
        for local_dir in [Path("data"), Path(__file__).parent.parent / "data"]:
            st_path = local_dir / "bot_state.json"
            if st_path.exists():
                try:
                    with open(st_path, "r", encoding="utf-8") as f:
                        st = json.load(f)
                    equity = float(st.get("equity", equity))
                    pos_data = st.get("positions", {})
                    positions_count = len(pos_data) if isinstance(pos_data, (dict, list)) else 0
                except Exception:
                    pass

    win_rate = (wins / total_trades * 100.0) if total_trades > 0 else 0.0
    return {
        "equity": equity,
        "positions": positions_count,
        "total_trades": total_trades,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "net_pnl": net_pnl,
    }


def send_telegram(data):
    if not TELEGRAM_BOT_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN not configured.", file=sys.stderr)
        return False

    now_ist = datetime.now(IST)
    date_str = now_ist.strftime("%d %b %Y | %I:%M %p IST")

    pnl_sign = "+" if data["net_pnl"] >= 0 else ""
    pnl_emoji = "🟢" if data["net_pnl"] >= 0 else "🔴"

    message = (
        f"📊 <b>AjayBot Daily Performance Report</b>\n"
        f"📅 <i>{date_str}</i>\n\n"
        f"💰 <b>Paper Equity:</b> ₹{data['equity']:,.2f}\n"
        f"{pnl_emoji} <b>Net PnL:</b> {pnl_sign}₹{data['net_pnl']:,.2f}\n"
        f"📈 <b>Open Positions:</b> {data['positions']}\n"
        f"📋 <b>Total Trades:</b> {data['total_trades']} (Wins: {data['wins']} | Losses: {data['losses']})\n"
        f"🎯 <b>Win Rate:</b> {data['win_rate']:.1f}%\n"
        f"⚡ <b>Leverage:</b> 20x | <b>Pairs:</b> BTC, ETH, SOL, DOGE, XRP, DOGS, AVAX\n\n"
        f"🤖 <i>Delivered 24/7 by Radha • Render + GitHub Actions</i>"
    )

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }).encode("utf-8")

    try:
        req = urllib.request.Request(url, data=payload)
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status == 200:
                print("Daily performance summary successfully dispatched to Telegram.")
                return True
    except Exception as e:
        print(f"Error sending Telegram message: {e}", file=sys.stderr)
        return False


def main():
    print("Generating Daily Performance Report...")
    data = fetch_performance()
    print(f"Performance: Equity=Rs.{data['equity']}, Positions={data['positions']}, Trades={data['total_trades']}")
    success = send_telegram(data)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
