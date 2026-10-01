# MEMORY — Ajay Rajbhar & Radha Operational Stack

- **User:** Ajay Rajbhar (Telegram Chat ID: `5238068527`, Home Channel)
- **Assistant:** Radha (राधा) — running on Telegram `@AiRadhabot` via Hermes Gateway on Render.
- **Goal:** Passive income via automated trading bot, financial independence from 9-5.
- **Cloud Architecture (Needs Laptop: False):**
  - Render Free Web Service: `hermes-gateway-wib4.onrender.com` (Uptime 24/7, low RAM <350MB).
  - GitHub Actions: `nothing12837-lang/ajaybot` (Runs paper trading every 15 min, monitor every 30 min, daily report at 10:30 AM IST).
  - Hugging Face: Private dataset `rareember/ajaybot-state` (Continuous sync every 5 minutes for mnemosyne DBs, state.db, memories, and trading state).
- **Trading Bot (AjayBot):**
  - Delta Exchange India paper trading across 7 symbols: `BTCUSD`, `ETHUSD`, `SOLUSD`, `DOGEUSD`, `XRPUSD`, `DOGSUSD`, `AVAXUSD`.
  - Initial Equity: ₹10,000, Leverage: 20x.
- **Scheduled Automations:**
  - 10:00 AM IST (04:30 UTC): Daily Morning News Brief (Indian headlines, UP, Punjab, Markets) sent to Telegram.
  - 10:30 AM IST (05:00 UTC): Daily Trading Performance Report sent to Telegram.
  - 07:00 AM IST (01:30 UTC): Train Reminder Check for Nov 4, 2026 journey (Train 12649 Sampark Kranti, Coach B1, Berth 18, PNR 4764141969).