Hermes Gateway runs on Render (URL managed via Render dashboard env vars; not hardcoded). GitHub repo: nothing12837-lang/ajaybot (private). Cron: */5 * * * * keep-alive ping running. All workflows: ajaybot-paper (2hr), ajaybot-monitor (2hr), ajaybot-24x7 (6hr), hermes-24x7 (5.5hr), hermes-keep-alive (5min), bot_heartbeat (hourly), daily_report (5:00 UTC), morning_news (4:30 UTC), train_reminder (1:30 UTC).
§
User Ajay Rajbhar is an entrepreneur building automated online businesses and algorithmic trading systems. He runs RareEmber dropshipping store and AjayBot algo trading system. He wants 70% min win rate, 8% monthly return, 10% max DD, min 10 trades/month for AjayBot.
§
Radha (AI Personal Manager) has optimized AjayBot config: increased min_confidence to 0.20, reduced risk_per_trade to 0.015, set max_dd_kill_pct to 0.10, added monthly_target_pct 0.08 and min_trades_per_month 10. Reset consecutive losses from 4 to 0. Created performance tracking and reporting systems.
§
Automated morning/evening reporting framework established. Manual morning check tasks removed as requested. All systems monitored via GitHub API.