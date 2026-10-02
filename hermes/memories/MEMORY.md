User Ajay Rajbhar is an entrepreneur building automated online businesses and algorithmic trading systems. He runs RareEmber dropshipping store and AjayBot algo trading system. He wants 70% min win rate, 8% monthly return, 10% max DD, min 10 trades/month for AjayBot.
§
Radha (AI Personal Manager) has optimized AjayBot config: increased min_confidence to 0.20, reduced risk_per_trade to 0.015, set max_dd_kill_pct to 0.10, added monthly_target_pct 0.08 and min_trades_per_month 10. Reset consecutive losses from 4 to 0. Created performance tracking and reporting systems.
§
Automated morning/evening reporting framework established. Manual morning check tasks removed as requested. All systems monitored via GitHub API.
§
On 2026-10-02T15:25:37Z, I successfully added the GEMINI_API_KEY secret to the GitHub repository nothing12837-lang/ajaybot. This secret enables Gemini AI analysis for the trading workflows.
§
# MEMORY — Ajay Rajbhar & Radha Operational Stack

- **User:** Ajay Rajbhar (Telegram Chat ID: `5238068527`)
- **Assistant:** Radha (AI Personal Manager) — operates via Hermes (GitHub Actions cron + local tools)
- **Goal:** AjayBot target: ≥70% win rate, ≥8% monthly return, ≤10% max drawdown, ≥10 trades/month
- **Systems:**
  - RareEmber dropshipping store: Next.js/Tailwind, localhost:3000 (C:/Users/ajay kumar/Downloads/dropship-store)
  - AjayBot algo trading: GitHub nothing12837-lang/ajaybot (paper trading, 20x leverage, BTC/ETH/SOL/etc.)
  - Hermes (self): Cron jobs in hermes-home/cron/, executed via GitHub Actions/workflows
- **Key Contacts:** Telegram chat ID 5238068527 (Ajay Rajbhar)
- **Notes:** Render service removed; AjayBot Heartbeat Check removed (redundant); all automation now via GitHub Actions and local agent workspace.