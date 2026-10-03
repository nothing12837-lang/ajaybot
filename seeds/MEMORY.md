# MEMORY — Ajay Rajbhar & Radha Operational Stack (CLEAN RETRAIN 03-Oct-2026; old corrupted memory wiped)

- **User:** Ajay Rajbhar (Telegram Chat ID: `5238068527`, Home Channel)
- **Assistant:** Radha — Telegram `@AiRadhabot` via GitHub workers. Model: `nvidia/nemotron-3-super-120b-a12b` (NVIDIA NIM). Full access: live metrics + GitHub control + internet search for all 3 bots.
- **Goal:** Passive income via automated trading bot, financial independence from 9-5.
- **Cloud Architecture (Needs Laptop: False):**
  - Render Free Web Service: `[DEPRECATED: hermes-gateway-wib4.onrender.com - Render service removed]` ([DEPRECATED] Was running on Render).
  - GitHub Actions: `nothing12837-lang/ajaybot` (Runs paper trading every 15 min, monitor every 30 min, daily report at 10:30 AM IST).
  - Hugging Face: Private dataset `rareember/ajaybot-state` (Continuous sync every 5 minutes for mnemosyne DBs, state.db, memories, and trading state).
- **Trading Bots (all paper, Delta Exchange India, 12x, crypto ONLY):**
  - AjayBot: 0.22 confidence, GitHub ping-pong workers 24x7.
  - tradebot: 0.22 confidence, 15-min paper cycles.
  - tradebot2: 0.30 confidence (conservative), 15-min paper cycles.
  - Initial Equity: ₹10,000 each. Targets: 70% win rate, 8% monthly, <10% drawdown.
- **Single brain rule:** GitHub worker is the ONLY Telegram poller. Render gateway stays SUSPENDED.
- **Scheduled Automations:**
  - 10:00 AM IST (04:30 UTC): Daily Morning News Brief (Indian headlines, UP, Punjab, Markets) sent to Telegram.
  - 10:30 AM IST (05:00 UTC): Daily Trading Performance Report sent to Telegram.
  - 07:00 AM IST (01:30 UTC): Train Reminder Check for Nov 4, 2026 journey (Train 12649 Sampark Kranti, Coach B1, Berth 18, PNR 4764141969).