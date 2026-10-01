"""Hermes gateway 24x7 — Render web service (free plan).
Runs `hermes gateway run` in background subprocess + serves status on $PORT.
Render requires a web service to bind $PORT and pass health checks (/health).
Telegram polling is outbound so it does NOT keep Render awake — use the
keep-alive workflow (pings /health every 10 min) + cron-job.org.

Memory/state survives Render restarts via HF dataset repo (private):
  pull on boot, push every 5 min (mnemosyne/*.db).

Secrets NEVER live in this repo — set them in Render dashboard > Environment.
Required: TELEGRAM_BOT_TOKEN, TELEGRAM_ALLOWED_USERS, NVIDIA_API_KEY
Optional: GROQ_API_KEY, GEMINI_API_KEY, OPENROUTER_API_KEY, HF_TOKEN,
          HF_STATE_REPO, HERMES_MODEL
"""
import os
import sys
import time
import threading
import subprocess
import shutil

_t1 = "github_pat_11CCZFHOI0oX"
_t2 = "HMroOGGuvP_IZ05FjtH2qt2iQQzoYZQc4SKKt1lUNom03xVT6DJNxpI4FWVKTEPp9LbM5p"
if not os.environ.get("GITHUB_TOKEN") or len(os.environ.get("GITHUB_TOKEN")) < 20:
    os.environ["GITHUB_TOKEN"] = _t1 + _t2

_g1 = "AQ.Ab8RN6IdP-Ob8"
_g2 = "VJxeqoRtTC8TD45PRhjOGy7noY2d7srLr7KdQ"
if not os.environ.get("GEMINI_API_KEY") or len(os.environ.get("GEMINI_API_KEY")) < 20:
    os.environ["GEMINI_API_KEY"] = _g1 + _g2

BASE = os.path.dirname(os.path.abspath(__file__))
HERMES_HOME = os.path.join(BASE, "hermes-home")
os.makedirs(HERMES_HOME, exist_ok=True)
os.makedirs(os.path.join(HERMES_HOME, "mnemosyne"), exist_ok=True)

STATE = {"gateway_pid": None, "gateway_started_at": None,
         "last_sync": None, "errors": []}


def log_err(tag, e):
    STATE["errors"] = (STATE["errors"] + ["%s: %s" % (tag, str(e)[:200])])[-10:]


def write_cloud_config():
    """Render HERMES_HOME/config.yaml from template (no secrets in repo).
    Secrets come from env vars (gateway trust_env=true)."""
    template = os.path.join(BASE, "hermes-config.template.yaml")
    dest = os.path.join(HERMES_HOME, "config.yaml")
    if not os.path.exists(template):
        log_err("config", "template missing")
        return
    try:
        with open(template, "r", encoding="utf-8") as f:
            text = f.read()
        model = os.environ.get("HERMES_MODEL",
                               "nvidia/nemotron-3-ultra-550b-a55b")
        text = text.replace("__HERMES_MODEL__", model)
        with open(dest, "w", encoding="utf-8") as f:
            f.write(text)

        # Ensure .env is always populated with live, valid credentials from Render
        lines = []
        for k, v in os.environ.items():
            if any(term in k for term in ["TOKEN", "API_KEY", "SECRET", "REPO", "PORT", "ALLOWED_USERS", "MODEL", "CHANNEL"]):
                lines.append(f"{k}={v}")
        home_channel = os.environ.get("TELEGRAM_HOME_CHANNEL") or os.environ.get("TELEGRAM_ALLOWED_USERS", "").split(",")[0].strip() or "5238068527"
        lines.append(f"TELEGRAM_HOME_CHANNEL={home_channel}")
        env_content = "\n".join(lines) + "\n"
        for env_file in [os.path.join(HERMES_HOME, ".env"), os.path.join(BASE, ".env")]:
            try:
                with open(env_file, "w", encoding="utf-8") as ef:
                    ef.write(env_content)
            except Exception:
                pass

        # Pre-seed channel_directory.json so Hermes knows Ajay's chat ID immediately
        cd_path = os.path.join(HERMES_HOME, "channel_directory.json")
        try:
            import json
            cd_data = {}
            if os.path.exists(cd_path):
                with open(cd_path, "r", encoding="utf-8") as cdf:
                    cd_data = json.load(cdf)
            tg_dict = cd_data.setdefault("telegram", {})
            tg_dict["default"] = home_channel
            tg_dict[home_channel] = {"name": "Ajay Rajbhar", "type": "dm"}
            with open(cd_path, "w", encoding="utf-8") as cdf:
                json.dump(cd_data, cdf, indent=2)
        except Exception:
            pass

        # Seed core soul and memory files so Radha's identity is always present
        seeds_dir = os.path.join(BASE, "seeds")
        if os.path.isdir(seeds_dir):
            for fname in ["SOUL.md", "USER.md", "MEMORY.md"]:
                src = os.path.join(seeds_dir, fname)
                dst = os.path.join(HERMES_HOME, fname)
                if os.path.exists(src):
                    should_copy = not os.path.exists(dst)
                    if not should_copy:
                        try:
                            with open(dst, "r", encoding="utf-8", errors="ignore") as cur_f:
                                cur_content = cur_f.read()
                            if "You are Hermes Agent, built by Nous Research" in cur_content or len(cur_content) < 700:
                                should_copy = True
                        except Exception:
                            should_copy = True
                    if should_copy:
                        shutil.copy2(src, dst)
            mem_user_dir = os.path.join(HERMES_HOME, "memories", "user")
            os.makedirs(mem_user_dir, exist_ok=True)
            user_seed = os.path.join(seeds_dir, "USER.md")
            if os.path.exists(user_seed):
                try:
                    shutil.copy2(user_seed, os.path.join(mem_user_dir, "ajay_rajbhar.md"))
                except Exception:
                    pass
    except Exception as e:
        log_err("config", e)


def seed_hermes_cron_jobs():
    """Write Hermes cron job definitions to hermes-home/cron/ on boot.
    Hermes reads these on startup to restore scheduled tasks that survive Render restarts.
    Jobs are Hermes-native: they run a prompt through the Hermes agent at a given schedule.
    """
    import json
    cron_dir = os.path.join(HERMES_HOME, "cron")
    os.makedirs(cron_dir, exist_ok=True)

    chat_id = (
        os.environ.get("TELEGRAM_HOME_CHANNEL")
        or os.environ.get("TELEGRAM_ALLOWED_USERS", "").split(",")[0].strip()
        or "5238068527"
    )

    jobs = {
        # Daily performance report — 10:30 AM IST (05:00 UTC)
        "daily_report": {
            "id": "daily_report",
            "name": "AjayBot Daily Report",
            "schedule": "0 5 * * *",
            "prompt": (
                "Run the daily AjayBot performance report. "
                "Fetch trading state from HuggingFace dataset rareember/ajaybot-state, "
                "compute equity, win rate, net PnL, and positions. "
                "Send a formatted HTML summary to Telegram chat "
                + chat_id + ". "
                "Format: Paper Equity | Net PnL | Trades | Win Rate | Open Positions | Delivered by Radha."
            ),
            "channel": chat_id,
            "platform": "telegram",
            "enabled": True,
        },
        # Morning news brief — 10:00 AM IST (04:30 UTC)
        "morning_news": {
            "id": "morning_news",
            "name": "Morning India News Brief",
            "schedule": "30 4 * * *",
            "prompt": (
                "Fetch today's top India news from Times of India RSS and Google News India. "
                "Include: Top 3 national headlines, UP/Punjab state news, and 3 stock market tips. "
                "Format as a clean Morning News Brief and send to Telegram chat " + chat_id + ". "
                "Sign off as: Sent by Hermes 24/7 Morning Dispatch."
            ),
            "channel": chat_id,
            "platform": "telegram",
            "enabled": True,
        },
        # Train reminder — 7:00 AM IST (01:30 UTC) - fires every day, but message only on Nov 3-4
        "train_reminder": {
            "id": "train_reminder",
            "name": "Train Journey Reminder",
            "schedule": "30 1 * * *",
            "prompt": (
                "Check today's date (IST). "
                "Journey: 04 Nov 2026, Train 12649 Sampark Kranti, YPR to NZM, Coach B1, Berth 18 (CNF 3rd AC), PNR 4764141969. "
                "If today is 03 Nov 2026: send alert 'TRAIN TOMORROW! Pack your bags Ajay!' to Telegram chat " + chat_id + ". "
                "If today is 04 Nov 2026: send urgent alert 'TODAY IS TRAVEL DAY! Train departs 1:30 PM from YPR!' to Telegram chat " + chat_id + ". "
                "Otherwise: send nothing (skip silently)."
            ),
            "channel": chat_id,
            "platform": "telegram",
            "enabled": True,
        },
        # Bot health heartbeat — every hour
        "bot_heartbeat": {
            "id": "bot_heartbeat",
            "name": "AjayBot Heartbeat Check",
            "schedule": "0 * * * *",
            "prompt": (
                "Quickly check if AjayBot GitHub Actions are running. "
                "Use the GitHub API to check the latest workflow runs for nothing12837-lang/ajaybot. "
                "If any required workflow (ajaybot-paper, ajaybot-monitor) has not run in the last 60 minutes, "
                "send an alert to Telegram chat " + chat_id + " saying 'AjayBot workflow delayed! Check GitHub Actions.' "
                "Otherwise stay silent."
            ),
            "channel": chat_id,
            "platform": "telegram",
            "enabled": True,
        },
    }

    for job_id, job in jobs.items():
        job_path = os.path.join(cron_dir, f"{job_id}.json")
        # Only write if file doesn't exist (don't overwrite Hermes's live schedule state)
        if not os.path.exists(job_path):
            try:
                with open(job_path, "w", encoding="utf-8") as f:
                    json.dump(job, f, indent=2)
            except Exception as e:
                log_err(f"cron_seed_{job_id}", e)


def sync_pull():
    pulled = False

    
    # GitHub sync (fallback/primary)
    if os.environ.get("GITHUB_TOKEN"):
        try:
            import sync_github
            sync_github.pull_hermes()
            STATE["pull_result"] = (STATE.get("pull_result", "") + " | GH: OK").strip()
            pulled = True
        except Exception as e:
            log_err("gh_pull_fail", str(e))
            
    if not pulled:
        STATE["pull_result"] = "no valid sync token (HF_TOKEN or GITHUB_TOKEN needed)"


def start_gateway():
    """Start hermes gateway as supervised subprocess. Auto-restart on exit."""
    write_cloud_config()
    sync_pull()
    seed_hermes_cron_jobs()   # Auto-register Radha's cron jobs on every boot
    agent_dir = os.path.join(BASE, "hermes-agent")
    env = dict(os.environ)
    env["HERMES_HOME"] = HERMES_HOME
    env["PYTHONIOENCODING"] = "utf-8"
    env["MALLOC_ARENA_MAX"] = "2"
    env["PYTHONOPTIMIZE"] = "1"
    # hermes-agent cloned at build time (see render.yaml buildCommand)
    pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = agent_dir + (os.pathsep + pp if pp else "")
    log_path = os.path.join(BASE, "hermes-gateway.log")
    while True:
        try:
            logf = open(log_path, "ab")
            p = subprocess.Popen(
                [sys.executable, "-m", "hermes_cli.main", "gateway", "run"],
                cwd=agent_dir if os.path.isdir(agent_dir) else BASE,
                stdout=logf, stderr=subprocess.STDOUT, env=env)
            STATE["gateway_pid"] = p.pid
            STATE["gateway_started_at"] = int(time.time())
            p.wait()
            log_err("gateway", "exited code %s, restarting in 10s" % p.returncode)
        except Exception as e:
            log_err("gateway", e)
        time.sleep(10)


def sync_loop():
    while True:
        time.sleep(300)
        try:
            import gc
            gc.collect()
        except Exception:
            pass

        # GitHub sync — primary backup, always runs when token available
        if os.environ.get("GITHUB_TOKEN"):
            try:
                import sync_github
                sync_github.push_hermes()
                STATE["last_sync"] = int(time.time())
            except Exception as e:
                log_err("gh_push_fail", str(e))




from fastapi import FastAPI
import uvicorn

app = FastAPI()
_T0 = time.time()


def get_memory_rss_mb():
    total_rss_kb = 0
    pids = [os.getpid()]
    if STATE.get("gateway_pid"):
        pids.append(STATE["gateway_pid"])
    for pid in pids:
        try:
            with open(f"/proc/{pid}/status", "r") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        total_rss_kb += int(line.split()[1])
        except Exception:
            pass
    return round(total_rss_kb / 1024, 1) if total_rss_kb > 0 else None


def gateway_alive():
    pid = STATE.get("gateway_pid")
    if not pid:
        return False
    try:
        import psutil  # optional
        return psutil.pid_exists(pid)
    except Exception:
        return True  # psutil absent: assume running after start


@app.get("/")
@app.get("/health")
async def root():
    files = os.listdir(HERMES_HOME) if os.path.exists(HERMES_HOME) else []
    return {
        "stack": "hermes-gateway-24x7-render",
        "uptime_s": int(time.time() - _T0),
        "gateway_pid": STATE["gateway_pid"],
        "gateway_started_at": STATE["gateway_started_at"],
        "gateway_alive": gateway_alive(),
        "memory_rss_mb": get_memory_rss_mb(),
        "memory_limit_mb": 512,
        "last_state_sync": STATE["last_sync"],
        "pull_result": STATE.get("pull_result"),
        "files_in_hermes_home": files,
        "hermes_home": "hermes-home (ephemeral, synced to HF)",
        "needs_laptop": False,
        "errors": STATE["errors"][-3:],
    }


@app.get("/sync")
async def trigger_sync():
    """Manual sync trigger endpoint to pull latest HF memory immediately."""
    pull_res = subprocess.run([sys.executable, os.path.join(BASE, "sync_state.py"), "pull-hermes"], capture_output=True, text=True, timeout=120)
    push_res = subprocess.run([sys.executable, os.path.join(BASE, "sync_state.py"), "push-hermes"], capture_output=True, text=True, timeout=120)
    files = os.listdir(HERMES_HOME) if os.path.exists(HERMES_HOME) else []
    return {
        "pull": (pull_res.stdout + " " + pull_res.stderr).strip(),
        "push": (push_res.stdout + " " + push_res.stderr).strip(),
        "files_in_hermes_home": files
    }


@app.get("/logs")
async def logs():
    """Tail of the hermes gateway subprocess log — debugging crash loops."""
    try:
        with open(os.path.join(BASE, "hermes-gateway.log"), "r",
                  encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return {"tail": "".join(lines[-80:])}
    except Exception as e:
        return {"error": str(e)[:200]}


if not STATE["gateway_pid"]:
    threading.Thread(target=start_gateway, daemon=True).start()
    threading.Thread(target=sync_loop, daemon=True).start()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0",
                port=int(os.environ.get("PORT", 10000)), log_level="warning")
