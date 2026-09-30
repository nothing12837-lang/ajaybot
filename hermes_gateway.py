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
    except Exception as e:
        log_err("config", e)


def sync_pull():
    if not os.environ.get("HF_TOKEN"):
        return
    try:
        res = subprocess.run([sys.executable, os.path.join(BASE, "sync_state.py"),
                        "pull-hermes"],
                       capture_output=True, text=True, timeout=120)
        STATE["pull_result"] = ((res.stdout or "") + " " + (res.stderr or "")).strip()
        if res.returncode != 0:
            log_err("pull_fail", res.stderr or res.stdout)
    except Exception as e:
        log_err("pull", e)


def start_gateway():
    """Start hermes gateway as supervised subprocess. Auto-restart on exit."""
    write_cloud_config()
    sync_pull()
    agent_dir = os.path.join(BASE, "hermes-agent")
    env = dict(os.environ)
    env["HERMES_HOME"] = HERMES_HOME
    env["PYTHONIOENCODING"] = "utf-8"
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
        if os.environ.get("HF_TOKEN"):
            try:
                res = subprocess.run(
                    [sys.executable, os.path.join(BASE, "sync_state.py"),
                     "push-hermes"],
                    capture_output=True, text=True, timeout=120)
                if res.returncode != 0:
                    log_err("push_fail", res.stderr or res.stdout)
                else:
                    STATE["last_sync"] = int(time.time())
            except Exception as e:
                log_err("push", e)


from fastapi import FastAPI
import uvicorn

app = FastAPI()
_T0 = time.time()


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
