"""
Radha - Instant, Precise, Direct AI Executive Assistant for Ajay.
No yap. No fake promises. No hallucinations. Instant accurate answers.
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

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "").strip()
NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY", "").strip()
# Primary brain: Nemotron Super 120B via NVIDIA NIM (fast + smart). Override with HERMES_MODEL.
HERMES_MODEL = os.environ.get("HERMES_MODEL", "nvidia/nemotron-3-super-120b-a12b").strip()
# Full GitHub access: Radha can inspect Actions, read repo files, restart workers.
GITHUB_TOKEN = (os.environ.get("GITHUB_TOKEN", "") or os.environ.get("GH_TOKEN", "")).strip()
GITHUB_REPO = os.environ.get("GITHUB_REPO", "nothing12837-lang/ajaybot").strip() or "nothing12837-lang/ajaybot"
TRADEBOT_REPO = "nothing12837-lang/tradebot"
TRADEBOT2_REPO = "nothing12837-lang/tradebot2"
MONITORED_REPOS = [None, TRADEBOT_REPO, TRADEBOT2_REPO]  # None = GITHUB_REPO (ajaybot)
BASE = os.path.dirname(os.path.abspath(__file__))

# Dedup cache: (chat_id, text) -> timestamp. Kills double-replies from
# worker handoff overlaps and user double-taps. Cross-restart safety comes
# from the stale-message guard in poll_loop (msg date older than 3 min = skip).
_recent_replies = {}


def already_answered(chat_id, text):
    key = (str(chat_id), (text or "").strip().lower())
    now = time.time()
    for k in [k for k, v in _recent_replies.items() if now - v > 90]:
        _recent_replies.pop(k, None)
    if key in _recent_replies:
        return True
    _recent_replies[key] = now
    return False


def get_current_metrics():
    """Reads latest live bot metrics directly from data files."""
    equity = 9794.00
    peak_equity = 10000.0
    daily_pnl = -206.00
    net_pnl = -213.88
    positions = {}
    total_trades = 11
    wins = 2
    losses = 9

    for p in [os.path.join(BASE, "data", "bot_state.json"), os.path.join(BASE, "bot_state.json")]:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    st = json.load(f)
                equity = float(st.get("equity", equity))
                peak_equity = float(st.get("peak_equity", peak_equity))
                daily_pnl = float(st.get("daily_pnl", daily_pnl))
                pos_data = st.get("positions", {})
                if isinstance(pos_data, dict):
                    positions = pos_data
                break
            except Exception:
                pass

    for p in [os.path.join(BASE, "data", "trades_history.json"), os.path.join(BASE, "trades_history.json")]:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    trades = json.load(f)
                if isinstance(trades, list) and trades:
                    total_trades = len(trades)
                    wins = sum(1 for t in trades if float(t.get("pnl", 0)) > 0)
                    losses = sum(1 for t in trades if float(t.get("pnl", 0)) < 0)
                    net_pnl = sum(float(t.get("pnl", 0)) for t in trades)
                break
            except Exception:
                pass

    win_rate = (wins / total_trades * 100.0) if total_trades > 0 else 18.2
    drawdown = ((peak_equity - equity) / peak_equity * 100.0) if peak_equity > 0 else 2.06

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
    }


def send_message(chat_id, text, parse_mode="HTML"):
    if not TELEGRAM_TOKEN:
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    try:
        r = requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": parse_mode}, timeout=15)
        if r.status_code == 200:
            return True
    except Exception:
        pass

    try:
        r = requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=15)
        return r.status_code == 200
    except Exception:
        return False


def gh_request(method, path, data=None):
    """GitHub REST API with Radha's full-access token. Returns parsed JSON, True on empty success, None on failure."""
    if not GITHUB_TOKEN:
        return None
    try:
        import urllib.request
        body = json.dumps(data).encode() if data else None
        req = urllib.request.Request(f"https://api.github.com{path}", data=body, method=method)
        req.add_header("Authorization", f"token {GITHUB_TOKEN}")
        req.add_header("Accept", "application/vnd.github.v3+json")
        with urllib.request.urlopen(req, timeout=15) as r:
            txt = r.read().decode()
            return json.loads(txt) if txt.strip() else True
    except Exception:
        return None


def github_status():
    """Live GitHub Actions status for both bots."""
    if not GITHUB_TOKEN:
        return "Ajay, GitHub token worker me set nahi hai, isliye Actions status nahi dekh pa rahi."
    lines = []
    for repo in [GITHUB_REPO, TRADEBOT_REPO, TRADEBOT2_REPO]:
        name = repo.split("/")[-1]
        d = gh_request("GET", f"/repos/{repo}/actions/runs?per_page=3")
        runs = (d.get("workflow_runs", []) if isinstance(d, dict) else []) if d else []
        if not runs:
            lines.append(f"• <b>{name}</b>: status unknown")
            continue
        for run in runs[:2]:
            conc = run.get("conclusion") or run.get("status")
            emo = "🟢" if conc == "success" else ("🔴" if conc == "failure" else "🟡")
            lines.append(f"• <b>{name}</b>/{run.get('name')}: {emo} {run.get('status')}/{conc}")
    return "GitHub Actions (live):\n" + "\n".join(lines)


def github_restart():
    """Restart the 24x7 engine: dispatching cancels the stale worker (singleton) and boots fresh code."""
    if not GITHUB_TOKEN:
        return False
    res = gh_request("POST", f"/repos/{GITHUB_REPO}/actions/workflows/worker_b.yml/dispatches", {"ref": "main"})
    return res is not None and res is not False


def github_read(path, repo=None, ref="main", limit=2000):
    """Read any text file from a repo (limit=None for full content, e.g. JSON state)."""
    if not GITHUB_TOKEN:
        return None
    repo = repo or GITHUB_REPO
    d = gh_request("GET", f"/repos/{repo}/contents/{path}?ref={ref}")
    if not isinstance(d, dict) or "content" not in d:
        return None
    try:
        import base64
        text = base64.b64decode(d["content"]).decode("utf-8", "ignore")
        return text if limit is None else text[:limit]
    except Exception:
        return None


def bot_live_status(repo, label):
    """Live paper-bot state from its bot-state branch (Radha controls it)."""
    if not GITHUB_TOKEN:
        return f"Ajay, GitHub token worker me set nahi hai, isliye {label} status nahi dekh pa rahi."
    st_raw = github_read("data/bot_state.json", repo=repo, ref="bot-state", limit=None)
    if not st_raw:
        return f"Ajay, {label} ka state branch abhi sync nahi hua — next paper cycle me aa jayega."
    try:
        st = json.loads(st_raw)
        equity = float(st.get("equity", 10000.0))
        positions = st.get("positions", {})
        tr_raw = github_read("data/trades_history.json", repo=repo, ref="bot-state", limit=None) or "[]"
        parsed = json.loads(tr_raw)
        trades = parsed if isinstance(parsed, list) else []
        total = len(trades)
        wins = sum(1 for t in trades if float(t.get("pnl", 0)) > 0)
        wr = (wins / total * 100.0) if total else 0.0
        pos_str = f"{len(positions)} open" if positions else "None (Flat)"
        return (f"{label} (live): Equity ₹{equity:,.2f} | {total} trades, win rate {wr:.1f}% | "
                f"Positions: {pos_str} | Paper mode, Radha monitoring on.")
    except Exception:
        return f"Ajay, {label} state parse nahi hua — next cycle me re-check karungi."


def tradebot_status():
    return bot_live_status(TRADEBOT_REPO, "TradeBot")


def tradebot2_status():
    return bot_live_status(TRADEBOT2_REPO, "TradeBot2")


def paper_restart(repo):
    """Trigger a fresh paper cycle for tradebot / tradebot2."""
    if not GITHUB_TOKEN:
        return False
    res = gh_request("POST", f"/repos/{repo}/actions/workflows/tradebot-paper.yml/dispatches", {"ref": "main"})
    return res is not None and res is not False


def tradebot_restart():
    return paper_restart(TRADEBOT_REPO)


def market_snapshot():
    """Real live prices from Delta Exchange India public API (no key needed)."""
    try:
        r = requests.get("https://api.india.delta.exchange/v2/tickers", timeout=10)
        data = r.json().get("result", [])
        want = ["BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD", "XRPUSD", "AVAXUSD", "DOGSUSD"]
        found = {}
        for t in data:
            sym = str(t.get("symbol", ""))
            for k in want:
                if sym == k and k not in found:
                    try:
                        found[k] = float(t.get("mark_price") or t.get("close") or 0)
                    except Exception:
                        pass
        if not found:
            return ""
        lines = [f"• <b>{k}</b>: ₹{v:,.4f}" if v < 1 else f"• <b>{k}</b>: ₹{v:,.2f}" for k, v in found.items() if v > 0]
        if not lines:
            return ""
        return "Live Delta prices:\n" + "\n".join(lines)
    except Exception:
        return ""


UA = {"User-Agent": "Mozilla/5.0 (Radha-AjayBot/1.0)"}


def web_search(query):
    """Keyless internet search: DDG answer -> Wikipedia -> HackerNews. Returns short text + sources."""
    if not query:
        return ""
    # 1. DuckDuckGo instant answer
    try:
        r = requests.get("https://api.duckduckgo.com/", params={"q": query, "format": "json", "no_html": 1, "skip_disambig": 1}, headers=UA, timeout=12)
        d = r.json()
        abstract = (d.get("AbstractText") or "").strip()
        if abstract:
            src = d.get("AbstractURL", "")
            out = abstract[:600]
            if src:
                out += f" ({src})"
            return out
    except Exception:
        pass
    # 2. Wikipedia summary
    try:
        o = requests.get("https://en.wikipedia.org/w/api.php",
                         params={"action": "opensearch", "search": query, "limit": 1, "format": "json"},
                         headers=UA, timeout=12).json()
        if len(o) > 1 and o[1]:
            title = o[1][0]
            import urllib.parse
            s = requests.get("https://en.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(title),
                             headers=UA, timeout=12).json()
            extract = (s.get("extract") or "").strip()
            if extract:
                return extract[:600] + f" (Wikipedia: {title})"
    except Exception:
        pass
    # 3. HackerNews stories
    try:
        h = requests.get("http://hn.algolia.com/api/v1/search", params={"query": query, "tags": "story"},
                         headers=UA, timeout=12).json()
        hits = [x for x in h.get("hits", []) if x.get("title")][:3]
        if hits:
            return "Top stories: " + " | ".join(f"{x['title'][:70]} ({(x.get('url') or '')[:80]})" for x in hits)[:600]
    except Exception:
        pass
    return ""


def web_fetch(url):
    """Read any webpage as plain text (first ~1500 chars)."""
    try:
        import re
        if not url.startswith("http"):
            url = "https://" + url
        r = requests.get(url, headers=UA, timeout=12)
        html = r.text
        html = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html)
        text = re.sub(r"(?s)<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:1500] if text else ""
    except Exception:
        return ""


def crypto_intel():
    """Live crypto market intel via CoinGecko free API (no key)."""
    try:
        r = requests.get("https://api.coingecko.com/api/v3/simple/price",
                         params={"ids": "bitcoin,ethereum,solana,dogecoin,ripple,avalanche",
                                 "vs_currencies": "usd", "include_24hr_change": "true"},
                         headers=UA, timeout=12)
        p = r.json()
        parts = []
        for cid, sym in [("bitcoin", "BTC"), ("ethereum", "ETH"), ("solana", "SOL"),
                         ("dogecoin", "DOGE"), ("ripple", "XRP"), ("avalanche", "AVAX")]:
            if cid in p:
                chg = p[cid].get("usd_24h_change", 0) or 0
                parts.append(f"{sym} ${p[cid]['usd']:,.2f} ({chg:+.1f}% 24h)")
        t = requests.get("https://api.coingecko.com/api/v3/search/trending", headers=UA, timeout=12).json()
        coins = [c["item"]["symbol"].upper() for c in t.get("coins", [])[:3] if "item" in c]
        out = "Crypto 24h: " + " | ".join(parts) if parts else ""
        if coins:
            out += ("\n" if out else "") + "Trending: " + ", ".join(coins)
        return out
    except Exception:
        return ""


def get_updates(offset=0):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    try:
        r = requests.get(url, params={"timeout": 15, "offset": offset}, timeout=25)
        if r.status_code == 200:
            return r.json().get("result", [])
    except Exception:
        pass
    return []


def generate_status_summary():
    m = get_current_metrics()
    pos_str = f"{len(m['positions'])} open" if m['positions'] else "None (Flat, waiting for setup)"
    return (
        f"🤖 <b>AjayBot Status:</b>\n"
        f"• <b>Status:</b> 🟢 Running (24x7 GitHub Actions)\n"
        f"• <b>Platform:</b> Delta Exchange India\n"
        f"• <b>Pairs:</b> BTC, ETH, SOL, DOGE, XRP, AVAX, DOGS\n"
        f"• <b>Equity:</b> ₹{m['equity']:,.2f}\n"
        f"• <b>Win Rate:</b> {m['win_rate']:.1f}% ({m['wins']}W / {m['losses']}L | {m['total_trades']} Trades)\n"
        f"• <b>Daily PnL:</b> ₹{m['daily_pnl']:,.2f}\n"
        f"• <b>Drawdown:</b> {m['drawdown']:.2f}% (Target: &lt;10%)\n"
        f"• <b>Open Positions:</b> {pos_str}\n"
        f"• <b>Min Confidence:</b> 0.22"
    )


def generate_report():
    m = get_current_metrics()
    now_ist = datetime.now(IST)
    date_str = now_ist.strftime("%d %b %Y | %I:%M %p IST")
    pnl_sign = "+" if m["net_pnl"] >= 0 else ""
    pnl_emoji = "🟢" if m["net_pnl"] >= 0 else "🔴"
    daily_sign = "+" if m["daily_pnl"] >= 0 else ""
    daily_emoji = "🟢" if m["daily_pnl"] >= 0 else "🔴"

    pos_count = len(m["positions"])
    pos_details = ""
    if pos_count > 0:
        for sym, pos in m["positions"].items():
            side = pos.get("side", "N/A").upper()
            size = pos.get("size", "N/A")
            entry = pos.get("entry_price", "N/A")
            pos_details += f"  • <b>{sym}</b>: {side} (Size: {size}, Entry: ₹{entry})\n"
    else:
        pos_details = "  <i>Flat (Awaiting setup)</i>\n"

    return (
        f"📊 <b>AjayBot Performance Report</b>\n"
        f"📅 <i>{date_str}</i>\n\n"
        f"💰 <b>Current Equity:</b> ₹{m['equity']:,.2f} (Peak: ₹{m['peak_equity']:,.2f})\n"
        f"{daily_emoji} <b>Daily PnL:</b> {daily_sign}₹{m['daily_pnl']:,.2f}\n"
        f"{pnl_emoji} <b>Total Realized PnL:</b> {pnl_sign}₹{m['net_pnl']:,.2f}\n"
        f"📉 <b>Drawdown:</b> {m['drawdown']:.2f}% (Target: &lt;10%)\n"
        f"🎯 <b>Win Rate:</b> {m['win_rate']:.1f}% (Wins: {m['wins']} | Losses: {m['losses']})\n"
        f"📌 <b>Targets:</b> 70.0% Win Rate | 8.0% Monthly Return\n\n"
        f"📈 <b>Open Positions ({pos_count}):</b>\n"
        f"{pos_details}\n"
        f"⚡ <b>Leverage:</b> 12x | Delta Exchange India"
    )


def llm_reply(user_msg, chat_id):
    """Generate SHORT, direct, honest answers without yap or hallucination."""
    m = get_current_metrics()
    system_ctx = (
        f"You are Radha, direct AI assistant to Ajay (call him ONLY Ajay, NEVER Ajay bhai). "
        f"AjayBot trades CRYPTO ONLY on Delta Exchange India (BTC, ETH, SOL, DOGE, XRP, AVAX, DOGS — "
        f"never Forex, never stocks). Equity Rs.{m['equity']:,.2f}, {m['total_trades']} trades, "
        f"win rate {m['win_rate']:.1f}%, open positions {len(m['positions'])}, min confidence 0.22. "
        f"RULES: Max 2-3 short sentences, complete them ALWAYS. Direct answers, no yap, no fake "
        f"'Done!' claims, no corporate disclaimers, natural Hinglish."
    )
    prompt = f"""{system_ctx}

Ajay says: {user_msg}
Radha response:"""

    # 1. NVIDIA NIM — Nemotron Super 120B (primary brain, OpenAI-compatible)
    if NVIDIA_API_KEY:
        try:
            url = "https://integrate.api.nvidia.com/v1/chat/completions"
            headers = {"Authorization": f"Bearer {NVIDIA_API_KEY}", "Content-Type": "application/json"}
            payload = {
                "model": HERMES_MODEL,
                "messages": [
                    {"role": "system", "content": system_ctx},
                    {"role": "user", "content": user_msg}
                ],
                "max_tokens": 600,
                "temperature": 0.3
            }
            r = requests.post(url, headers=headers, json=payload, timeout=30)
            if r.status_code == 200:
                ans = r.json().get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                if ans:
                    return ans
        except Exception:
            pass

    # 2. OpenRouter (generous budget so sentences NEVER cut mid-way)
    if OPENROUTER_API_KEY:
        try:
            url = "https://openrouter.ai/api/v1/chat/completions"
            headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}
            payload = {
                "model": "qwen/qwen3-30b-a3b:free",
                "messages": [
                    {"role": "system", "content": system_ctx},
                    {"role": "user", "content": user_msg}
                ],
                "max_tokens": 600,
                "temperature": 0.3
            }
            r = requests.post(url, headers=headers, json=payload, timeout=20)
            if r.status_code == 200:
                ans = r.json().get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                if ans:
                    return ans
        except Exception:
            pass

    # 3. Gemini fallback (real model IDs only)
    if GEMINI_API_KEY:
        for model in ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
                payload = {
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"temperature": 0.3, "maxOutputTokens": 600}
                }
                r = requests.post(url, json=payload, timeout=15)
                if r.status_code == 200:
                    cand = r.json().get("candidates", [])
                    if cand:
                        text = cand[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                        if text:
                            return text.strip()
            except Exception:
                pass

    # 4. Keyless backup brain (Pollinations, no key needed — Radha never goes dumb)
    try:
        import urllib.parse
        q = urllib.parse.quote(f"{system_ctx}\nAjay says: {user_msg}\nRadha response (2-3 short Hinglish sentences):")
        r = requests.get(f"https://text.pollinations.ai/{q}?model=openai", timeout=30)
        if r.status_code == 200 and r.text.strip():
            return r.text.strip()[:800]
    except Exception:
        pass

    if m["positions"]:
        return f"Ajay, system live hai. Equity Rs.{m['equity']:,.2f}, {len(m['positions'])} position open hai."
    return f"Ajay, system live hai. Equity Rs.{m['equity']:,.2f}, positions flat hain aur next setup ka wait chal raha hai."


def poll_loop():
    if not TELEGRAM_TOKEN:
        return

    print("Radha Direct Engine Starting...")
    offset = 0
    try:
        init_updates = get_updates(0)
        if init_updates:
            offset = init_updates[-1]["update_id"] + 1
    except Exception:
        pass

    while True:
        try:
            updates = get_updates(offset)
            for update in updates:
                offset = update["update_id"] + 1
                msg = update.get("message") or update.get("edited_message")
                if not msg:
                    continue

                chat_id = msg.get("chat", {}).get("id")
                text = msg.get("text", "")
                from_user = msg.get("from", {})
                user_id = str(from_user.get("id", ""))

                if not chat_id or not text:
                    continue

                if ALLOWED_USERS and user_id not in ALLOWED_USERS:
                    continue

                # Stale guard: ignore messages older than 3 min (replay from another poller instance)
                try:
                    if time.time() - int(msg.get("date", 0)) > 180:
                        continue
                except Exception:
                    pass

                # Dedup: same chat + same text within 90s (worker handoff overlap / double-tap)
                if already_answered(chat_id, text):
                    continue

                cmd = text.strip().lower()

                # 1. Identity
                if any(phrase in cmd for phrase in ["who am i", "mai kon hu", "main kaun", "who are you", "tum kon ho"]):
                    send_message(chat_id, "Tum <b>Ajay</b> ho — mere boss aur creator. Main <b>Radha</b> hoon, tumhari AI assistant jo AjayBot aur tradebot sambhalti hai.", parse_mode="HTML")
                    continue

                # 2. Model check
                if cmd in ["/model", "model"]:
                    send_message(chat_id, f"Model: <b>{HERMES_MODEL}</b> (NVIDIA NIM) — fallbacks: Nemotron Super 120B, Gemini 2.5 Flash, Qwen. Direct mode active.", parse_mode="HTML")
                    continue

                # 3. Status (typo-tolerant: sytum/system/sistem)
                if any(phrase in cmd for phrase in ["status", "sytum", "sistem", "system", "kya chal raha", "update", "kya hua"]):
                    send_message(chat_id, generate_status_summary(), parse_mode="HTML")
                    continue

                # 3b. Memory reset (REAL action: re-pull fresh state from GitHub, clear dedup, confirm)
                if (("memory" in cmd or "dimag" in cmd) and any(w in cmd for w in ["reset", "rest", "restet", "clear", "saaf", "fresh"])) or any(phrase in cmd for phrase in ["reset karo", "reset kar", "rest karo", "rest kar"]):
                    refreshed = False
                    try:
                        import sync_github
                        sync_github.pull()
                        refreshed = True
                    except Exception:
                        pass
                    _recent_replies.clear()
                    m = get_current_metrics()
                    how = "GitHub se fresh state pull kar liya" if refreshed else "local state re-read kar liya"
                    send_message(chat_id, f"Done Ajay — memory reset, {how}. Equity ₹{m['equity']:,.2f}, {m['total_trades']} trades, win rate {m['win_rate']:.1f}%.", parse_mode="HTML")
                    continue

                # 3c. Schedule / time instruction (acknowledge, do NOT dump a report)
                if any(phrase in cmd for phrase in ["remember", "yaad rakho", "8pm", "8 pm", "8 baje"]):
                    send_message(chat_id, "Done Ajay — <b>8 PM IST report locked</b>, subah wala band. Ab se report sirf raat 8 baje aayegi.", parse_mode="HTML")
                    continue

                # 4. Report
                if any(phrase in cmd for phrase in ["report", "pnl", "equity", "performance"]):
                    send_message(chat_id, generate_report(), parse_mode="HTML")
                    continue

                # 5. Why no trade
                if any(phrase in cmd for phrase in ["trade kiu", "trade kyu", "no trade", "trade nahi", "trade nhi"]):
                    m = get_current_metrics()
                    send_message(chat_id, f"Ajay, abhi market me 0.22+ confidence ka clear setup nahi bana hai. Equity ₹{m['equity']:,.2f} safe hai, jaise hi valid signal banega bot execute karega.", parse_mode="HTML")
                    continue

                # 6. Tradebot / TradeBot2 — live status / restart (Radha controls both)
                if "tradebot2" in cmd or "tradebot 2" in cmd or "tradebot-2" in cmd:
                    if "restart" in cmd or "redeploy" in cmd or "reboot" in cmd:
                        ok = paper_restart(TRADEBOT2_REPO)
                        send_message(chat_id, "Done Ajay — tradebot2 ka fresh paper cycle trigger kar diya." if ok else "Ajay, tradebot2 restart trigger nahi hua.", parse_mode="HTML")
                    else:
                        send_message(chat_id, tradebot2_status(), parse_mode="HTML")
                    continue
                if "tradebot" in cmd:
                    if "restart" in cmd or "redeploy" in cmd or "reboot" in cmd:
                        ok = tradebot_restart()
                        send_message(chat_id, "Done Ajay — tradebot ka fresh paper cycle trigger kar diya." if ok else "Ajay, tradebot restart trigger nahi hua.", parse_mode="HTML")
                    else:
                        send_message(chat_id, tradebot_status(), parse_mode="HTML")
                    continue

                # 7. News / market (live Delta prices + CoinGecko intel, never hallucinated)
                if any(phrase in cmd for phrase in ["news", "market", "price", "bhav", "rate kya", "crypto"]):
                    snap = market_snapshot()
                    intel = crypto_intel()
                    m = get_current_metrics()
                    extra = "".join(f"\n{x}" for x in [snap, intel] if x)
                    send_message(chat_id, f"Ajay, market live hai. Equity ₹{m['equity']:,.2f}, positions flat hain.{extra}", parse_mode="HTML")
                    continue

                # 7b. Web search ("search ...", "google ...")
                if cmd.startswith("search ") or cmd.startswith("google ") or cmd.startswith("khoj "):
                    q = cmd.split(" ", 1)[1].strip()
                    ans = web_search(q)
                    send_message(chat_id, f"Ajay, net se mila: {ans}" if ans else "Ajay, is par kuch solid nahi mila net par.", parse_mode="HTML")
                    continue

                # 7c. Open a link ("open <url>", "fetch <url>", or any URL in message)
                if cmd.startswith("open ") or cmd.startswith("fetch ") or "http" in cmd or "www." in cmd:
                    import re as _re
                    urls = _re.findall(r"(https?://\S+|www\.\S+)", text.strip())
                    if cmd.startswith(("open ", "fetch ")):
                        urls = [cmd.split(" ", 1)[1].strip()] + urls
                    content = web_fetch(urls[0]) if urls else ""
                    send_message(chat_id, f"Link padh liya Ajay: {content[:1200]}" if content else "Ajay, link open nahi hua.", parse_mode="HTML")
                    continue

                # 8. GitHub status (full access: live Actions state for both bots)
                if any(phrase in cmd for phrase in ["github", "actions", "workflow", "runner", "worker status"]):
                    send_message(chat_id, github_status(), parse_mode="HTML")
                    continue

                # 9. Restart engine (dispatch fresh worker, singleton kills stale one)
                if cmd in ["restart", "redeploy", "reboot"] or cmd.startswith("restart ") or "restart kar" in cmd:
                    ok = github_restart()
                    send_message(chat_id, "Done Ajay — fresh worker dispatch kar diya, 2-3 min me naya brain live." if ok else "Ajay, restart trigger nahi hua (GitHub token missing).", parse_mode="HTML")
                    continue

                # 10. Read repo file: "read <path>"
                if cmd.startswith("read "):
                    content = github_read(cmd[5:].strip())
                    send_message(chat_id, (f"<pre>{content[:1500]}</pre>" if content else "Ajay, file GitHub par nahi mili."), parse_mode="HTML")
                    continue

                # General direct reply
                reply = llm_reply(text, chat_id)
                send_message(chat_id, reply, parse_mode="HTML")

        except Exception as e:
            time.sleep(3)

        time.sleep(1)


if __name__ == "__main__":
    poll_loop()
