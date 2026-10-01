# HERMES + KRONOS - FULL SESSION MEMORY (READ EVERY START)
> This file is read by Hermes Agent on every session. Update after each chat.

## WHO WE ARE
- User: Ajay Rajbhar (5238068527) - Goal: Passive income via trading bot, free from 9-5, basic life
- Assistant: Hermes Agent (Radha on Telegram @AiRadhabot) - built by Nous Research, runs on Nvidia NIM
- Past project: KronosBot — REMOVED 24.09.2026 per Ajay (stopped, do not resume)

## WHAT WE DID (21.09.2026)
1. YouTube: https://youtu.be/oZ-766itSvM - Hermes Masterclass Hindi - Fetched captions 1642 snippets via youtube-transcript-api, saved to C:\Users\AJAYKU~1\AppData\Local\Temp\opencode\transcript_oZ-766itSvM_hi.txt
2. Hermes Install: Native Windows to %LOCALAPPDATA%\hermes via install.ps1 -SkipSetup, v0.21.3, Python 3.11, Node 22
3. Gemini API: Primary nvidia/nemotron-3-ultra-550b-a55b via NVIDIA_API_KEY=nvapi-sN2ID... (81 models, 550b chosen for quality, Super 120b fastest 8.9s). Also pooled 2x Gemini AQ.Ab8RN6... (GOOGLE_API_KEY + GEMINI_API_KEY + gemini-2) for 40/min fallback, but all hit 429 free tier 20/min
4. Telegram: Bot @AiRadhabot 8717067478:AAGvw... Chat 5238068527, gateway PID 11316, Startup Hermes_Gateway.vbs, polling healthy
5. Groq: gsk_C7X... for auxiliary compression/title -> 14k/day free, qwen/qwen3.8-27b 32k->128k
6. OpenRouter: sk-or-v1-a9d6... 446 models, 21 free, but hit free-models-per-day 429 until 05:30, fallback nex-agi/liquid tried, now fallback cleared to only Nvidia
7. Nvidia NIM: nvapi-sN2ID... 81 models, chose 550b Ultra for Kronos (1M context), Super 120b fastest
8. Kronos Fixes: Killed hanging python (7260:8080), fixed config.yaml min_confidence 0.10->0.35, min_agents_agree 1->2, risk 0.02->0.01, max_daily 0.05->0.02, verified http://localhost:8080/api/status running equity 10000
9. Rate Limits: Gemini 20/min, OpenRouter free 200/day, Groq 14k/day, Nvidia 503 overloaded retries 5, auto_recovery 10, fallback [] to keep trying not cancel
10. Big Works Fix: Prompt 59k ->22k via disabled_toolsets, then back to [] for big, compression to nvidia 1M, threshold 0.75, target 0.3, to handle Kronos 77339 tokens without 413
11. Gateway Issues: taskkill /F /IM python.exe killed Hermes too -> SIGKILL UNCLEANLY -> No gateway -> restarted PID 8960, 9940, 11316, etc. Fix: use taskkill /PID <kronos> only
12. Memory Issue: After restart/gateway stop, auto-reset due to 413 + compression fails -> forget. Fixed by 1M context and not using small qwen fallback

## CURRENT WORKING CONFIG (C:\Users\ajay kumar\AppData\Local\hermes\config.yaml)
- model.provider: nvidia, model.default: nvidia/nemotron-3-ultra-550b-a55b, providers.nvidia.context_length: 1000000
- fallback_providers: [] (only Nvidia, keep trying 5 retries)
- agent.api_max_retries: 5, auto_recovery_cycles: 10, max_turns: 500
- auxiliary.compression.provider: nvidia, model: same 550b
- worktree: true, max_concurrent_sessions: 5, busy_input_mode: interrupt (Telegram multi-task)
- Kronos config.yaml: paper mode, DOGSUSD/BTCUSD 15m, min_confidence 0.35, min_agents_agree 2, paper_equity 10000

## SECRETS (C:\Users\ajay kumar\AppData\Local\hermes\.env and Kronos\.env)
- GOOGLE_API_KEY=AQ.Ab8RN6IdP... , GEMINI_API_KEY same, gemini-2=AQ.Ab8RN6JNHJT...
- GROQ_API_KEY=gsk_C7X..., OPENROUTER_API_KEY=sk-or-v1-a9d6..., NVIDIA_API_KEY=nvapi-sN2ID...
- Kronos .env: DELTA_API_KEY=ode6..., TELEGRAM_BOT_TOKEN same, GEMINI_API_KEY same

## KRONOS STRUCTURE (STRUCTURE.md)
- bot/adaptive_bot.py, arbiter, risk, execution, signals (kronos, smc, liquidity...), data/delta_client, webui/app.py, tests, etc.
- WebUI 8080 + bot together via start_all.py asyncio.gather

## NEXT TASK FOR HERMES
- (24.09.2026) KronosBot REMOVED per Ajay — processes stopped, do NOT resume or auto-start; await Ajay's next direction
- (30.09.2026) Hermes gateway moved to Render free: hermes-gateway-wib4.onrender.com (gateway_alive:true, model nemotron-3-ultra-550b). Laptop gateway STOPPED to avoid Telegram polling conflict — only restart with `hermes gateway run --replace` if Render dies. Deploy repo = github.com/nothing12837-lang/ajaybot (PUBLIC, branch main, local mirror Downloads/vps-deploy/space). Pushed 30.09: fixed buildCommand, checkpoint_required=false, /logs route, removed app/config/config.yaml from tracking. SECURITY: repo public + old commit had live bot token + Gemini key in history -> MUST revoke via BotFather and rotate Gemini key.
- Use Telegram @AiRadhabot /new + targeted reads, keep laptop on, avoid broad taskkill

## RULES TO REMEMBER
- Low-end laptop no GPU -> use cloud Nvidia/Groq/Gemini, not local Ollama
- Keep free: Groq 14k/day, OpenRouter free after 05:30, Gemini 20/min pooled
- Big works need 1M context, small tasks ok with 32k, but Kronos needs 1M
- After gateway restart, read this file first

Last updated: 24.09.2026 by Hermes — KronosBot removed per Ajay


## LATEST SYSTEM STATUS UPDATE (01.10.2026 11:30 IST)
- Fee modeling code pushed to GitHub (commits fc72796 and 7a2d2c1). Paper trading runs include taker fees (0.05%), maker fees (0.02%), and slippage (0.01%).
- AjayBot Monitor workflow active (.github/workflows/ajaybot-monitor.yml) and dedicated Daily Report workflow (.github/workflows/daily-report.yml) scheduled for 10:30 AM IST (05:00 UTC) with scripts/daily_report.py.
- 10:00 AM IST Morning News Brief job ACTIVE (.github/workflows/morning-news.yml + scripts/morning_news.py) covering National, UP, Punjab, and Markets.
- Train Reminder Check configured (scripts/train_reminder.py) for Ajay's journey on 04-Nov-2026 (Train 12649 Sampark Kranti Express from YPR to NZM, Coach B1 Berth 18, PNR 4764141969).
- Auxiliary compression updated to Google Gemini Flash to eliminate 600s timeout auto-resets.
- TELEGRAM_HOME_CHANNEL set to Ajay's chat 5238068527 to permanently eliminate "No home channel set" notices.
- SOUL.md and USER.md enriched so Radha greets Ajay warmly and recognizes him across all resets.
