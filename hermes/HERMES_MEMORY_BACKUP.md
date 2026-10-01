# HERMES + KRONOS - FULL SESSION MEMORY (READ EVERY START)
> This file is read by Hermes Agent on every session. Update after each chat.

## WHO WE ARE
- User: Ajay Rajbhar (5238068527) - Goal: Passive income via trading bot, free from 9-5, basic life
- Assistant: Hermes Agent (Radha on Telegram @AiRadhabot) - built by Nous Research, runs on Nvidia NIM
- Project: KronosBot at C:\Users\ajay kumar\Downloads\KronosBot - Adaptive 10-agent trading bot for Delta Exchange India (DOGSUSD, BTCUSD)

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
- Lead KronosBot to perfect working, generate trading bot for passive income, audit safety/risk/execution small chunks (1 file/turn), not full ls find
- Use Telegram @AiRadhabot /new + targeted reads, keep laptop on, avoid broad taskkill

## RULES TO REMEMBER
- Low-end laptop no GPU -> use cloud Nvidia/Groq/Gemini, not local Ollama
- Keep free: Groq 14k/day, OpenRouter free after 05:30, Gemini 20/min pooled
- Big works need 1M context, small tasks ok with 32k, but Kronos needs 1M
- After gateway restart, read this file first

Last updated: 21.09.2026 23:26 by Hermes setup
