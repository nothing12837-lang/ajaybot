"""AjayBot 24x7  Render web service (free plan).
Runs AjayBot trading in background subprocess + serves status on $PORT.
Keep-awake: external pinger (cron-job.org) hits / every 10 min."""
import os
import sys
import json
import time
import threading
import subprocess

BASE = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(BASE, "data")
os.makedirs(STATE_DIR, exist_ok=True)

STATE = {"bot_pid": None, "bot_started_at": None, "last_sync": None, "errors": []}


def log_err(tag, e):
    STATE["errors"] = (STATE["errors"] + [f"{tag}: {str(e)[:200]}"])[-10:]


def start_bot():
    """Run AjayBot (trading loop + internal webui on 8081)."""
    try:
        p = subprocess.Popen([sys.executable, os.path.join(BASE, "main.py")],
                            cwd=BASE,
                            stdout=open(os.path.join(BASE, "ajaybot.log"), "ab"),
                            stderr=subprocess.STDOUT)
        STATE["bot_pid"] = p.pid
        STATE["bot_started_at"] = int(time.time())
    except Exception as e:
        log_err("bot", e)


def sync_loop():
    """Pull state on boot, push every 5 min to HF dataset repo."""
    if os.environ.get("HF_TOKEN"):
        try:
            subprocess.run([sys.executable, os.path.join(BASE, "sync_state.py"), "pull"],
                           capture_output=True, text=True, timeout=120)
        except Exception as e:
            log_err("pull", e)
    while True:
        time.sleep(300)
        if os.environ.get("HF_TOKEN"):
            try:
                subprocess.run([sys.executable, os.path.join(BASE, "sync_state.py"), "push"],
                               capture_output=True, text=True, timeout=120)
                STATE["last_sync"] = int(time.time())
            except Exception as e:
                log_err("push", e)


import requests
from fastapi import FastAPI
import uvicorn

app = FastAPI()
_T0 = time.time()


@app.get("/")
@app.get("/health")
async def root():
    try:
        r = requests.get("http://localhost:8081/api/status", timeout=5)
        bot = r.json()
    except Exception as e:
        bot = {"unreachable": str(e)[:80]}
    return {
        "stack": "ajaybot-24x7-render",
        "space_uptime_s": int(time.time() - _T0),
        "bot_pid": STATE["bot_pid"],
        "bot_started_at": STATE["bot_started_at"],
        "last_state_sync": STATE["last_sync"],
        "ajaybot": bot,
        "errors": STATE["errors"][-3:],
    }


if not STATE["bot_pid"]:
    threading.Thread(target=start_bot, daemon=True).start()
    threading.Thread(target=sync_loop, daemon=True).start()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)), log_level="warning")
