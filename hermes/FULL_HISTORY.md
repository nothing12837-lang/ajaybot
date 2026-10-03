# FULL HISTORY — Retrained Baseline (03 Oct 2026)

> Previous full history archived & wiped (corrupted memory era). Fresh start below.

- 03-Oct-2026: Memory wipe + retrain. Deleted stale sessions/logs/skills DBs/cron state from bot-state branch. Reseeded clean SOUL/USER/MEMORY.
- Radha chat engine (`radha_telegram.py`) runs on GitHub workers: Nemotron 550B primary, real model IDs, 600-token budget, live metrics, GitHub control, internet search, anti-duplicate guards.
- tradebot stripped to pure paper bot; tradebot2 created (conservative 0.30). Both green.
- Single-poller rule: Render Hermes gateway must stay SUSPENDED — GitHub worker is the only Telegram poller.
- SECURITY: hardcoded tokens removed from repo; rotate Telegram/Gemini/NVIDIA keys (were in public git history).
