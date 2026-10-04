#!/usr/bin/env python3
"""Daily Trading Performance Report for Ajay (8:00 AM / 8:00 PM IST).
Fetches latest trading state from data/bot_state.json and data/trades_history.json,
computes key metrics (equity, open positions, win rate, net PnL, drawdown),
and dispatches a clean, executive HTML digest directly to Ajay's Telegram.
"""
import os
import sys
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path

IST = timezone(timedelta(hours=5, minutes=30))
BASE = Path(__file__).parent.parent

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_ALLOWED_USERS = os.environ.get("TELEGRAM_ALLOWED_USERS", "5238068527").strip()
CHAT_ID = TELEGRAM_ALLOWED_USERS.split(",")[0].strip() if TELEGRAM_ALLOWED_USERS else "5238068527"


def fetch_performance():
    equity = 10000.0
    peak_equity = 10000.0
    daily_pnl = 0.0
    positions = {}
    total_trades = 0
    wins = 0
    losses = 0
    net_pnl = 0.0
    trades_list = []

    # 1. Read bot_state.json
    for p in [BASE / "data" / "bot_state.json", Path("data/bot_state.json"), BASE / "bot_state.json"]:
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    st = json.load(f)
                equity = float(st.get("equity", equity))
                peak_equity = float(st.get("peak_equity", peak_equity))
                daily_pnl = float(st.get("daily_pnl", daily_pnl))
                positions = st.get("positions", {})
                if isinstance(positions, list):
                    positions = {pos.get("symbol", f"pos_{i}"): pos for i, pos in enumerate(positions)}
                print(f"Loaded bot_state from {p}")
                break
            except Exception as e:
                print(f"Error reading {p}: {e}")

    # 2. Read trades_history.json
    for p in [BASE / "data" / "trades_history.json", Path("data/trades_history.json"), BASE / "trades_history.json"]:
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    trades = json.load(f)
                if isinstance(trades, list):
                    trades_list = trades
                    total_trades = len(trades)
                    for t in trades:
                        pnl = float(t.get("pnl", 0.0))
                        net_pnl += pnl
                        if pnl > 0:
                            wins += 1
                        elif pnl < 0:
                            losses += 1
                print(f"Loaded {total_trades} trades from {p}")
                break
            except Exception as e:
                print(f"Error reading {p}: {e}")

    win_rate = (wins / total_trades * 100.0) if total_trades > 0 else 0.0
    drawdown = ((peak_equity - equity) / peak_equity * 100.0) if peak_equity > 0 else 0.0

    return {
        "equity": equity,
        "peak_equity": peak_equity,
        "daily_pnl": daily_pnl,
        "net_pnl": net_pnl,
        "positions": positions,
        "total_trades": total_trades,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "drawdown": drawdown,
        "recent_trades": trades_list[-3:] if trades_list else [],
    }


def send_telegram(data):
    if not TELEGRAM_BOT_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN is not set!", file=sys.stderr)
        return False

    now_ist = datetime.now(IST)
    date_str = now_ist.strftime("%d %b %Y | %I:%M %p IST")

    pnl_sign = "+" if data["net_pnl"] >= 0 else ""
    pnl_emoji = "🟢" if data["net_pnl"] >= 0 else "🔴"
    daily_sign = "+" if data["daily_pnl"] >= 0 else ""
    daily_emoji = "🟢" if data["daily_pnl"] >= 0 else "🔴"

    pos_count = len(data["positions"])
    pos_details = ""
    if pos_count > 0:
        for sym, pos in data["positions"].items():
            side = pos.get("side", "N/A").upper()
            size = pos.get("size", "N/A")
            entry = pos.get("entry_price", "N/A")
            pos_details += f"  • <b>{sym}</b>: {side} (Size: {size}, Entry: ₹{entry})\n"
    else:
        pos_details = "  <i>None currently open (flat)</i>\n"

    recent_trade_text = ""
    if data["recent_trades"]:
        recent_trade_text = "\n📋 <b>Recent Trades:</b>\n"
        for t in data["recent_trades"]:
            sym = t.get("symbol", "N/A")
            side = t.get("side", "N/A").upper()
            pnl = float(t.get("pnl", 0.0))
            t_sign = "+" if pnl >= 0 else ""
            t_emoji = "✅" if pnl >= 0 else "❌"
            recent_trade_text += f"  {t_emoji} {sym} {side}: {t_sign}₹{pnl:,.2f}\n"

    message = (
        f"📊 <b>AjayBot Executive Performance Report</b>\n"
        f"📅 <i>{date_str}</i>\n\n"
        f"💰 <b>Current Equity:</b> ₹{data['equity']:,.2f} (Peak: ₹{data['peak_equity']:,.2f})\n"
        f"{daily_emoji} <b>Daily PnL:</b> {daily_sign}₹{data['daily_pnl']:,.2f}\n"
        f"{pnl_emoji} <b>Total Realized PnL:</b> {pnl_sign}₹{data['net_pnl']:,.2f}\n"
        f"📉 <b>Current Drawdown:</b> {data['drawdown']:.2f}% (Target: &lt;10%)\n\n"
        f"🎯 <b>Win Rate:</b> {data['win_rate']:.1f}% (Wins: {data['wins']} | Losses: {data['losses']})\n"
        f"📌 <b>Target Win Rate:</b> 70.0% | <b>Monthly Target:</b> 8.0%\n\n"
        f"📈 <b>Open Positions ({pos_count}):</b>\n"
        f"{pos_details}"
        f"{recent_trade_text}\n"
        f"⚡ <b>Leverage:</b> 12x | <b>Pairs:</b> BTC, ETH, SOL, DOGE, XRP, AVAX\n"
        f"🛡️ <b>Strategy Optimization:</b> Confidence threshold set to 0.22 to filter weak signals.\n\n"
        f"🤖 <i>AjayBot • 24x7 GitHub Actions Engine</i>"
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
        with urllib.request.urlopen(req, timeout=20) as resp:
            if resp.status == 200:
                print("Executive report successfully dispatched to Telegram.")
                return True
    except Exception as e:
        print(f"Error sending Telegram message: {e}", file=sys.stderr)
        return False


def main():
    print("Generating AjayBot Executive Report...")
    data = fetch_performance()
    print(f"Metrics: Equity=Rs.{data['equity']:,.2f}, Total Trades={data['total_trades']}, WinRate={data['win_rate']:.1f}%")
    success = send_telegram(data)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
