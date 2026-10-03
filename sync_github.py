"""
GitHub-based state sync for AjayBot + Hermes memory.
Replaces / complements HF sync. Uses GitHub API directly (no extra packages needed).

State is stored in a dedicated branch 'bot-state' of the same repo
(nothing12837-lang/ajaybot) so no separate private repo needed.

Required env var: GITHUB_TOKEN (PAT with repo scope OR built-in $GITHUB_TOKEN in Actions)
Optional env var: GITHUB_REPO  (default: nothing12837-lang/ajaybot)
                  GITHUB_STATE_BRANCH (default: bot-state)

Usage:
    python sync_github.py push-hermes
    python sync_github.py pull-hermes
    python sync_github.py push           # bot state only
    python sync_github.py pull           # bot state only
"""

from __future__ import annotations
import base64
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import time
import urllib.request
import urllib.parse
from pathlib import Path
from typing import Optional

#  Config 
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO  = os.environ.get("GITHUB_REPO", "nothing12837-lang/ajaybot")
STATE_BRANCH = os.environ.get("GITHUB_STATE_BRANCH", "bot-state")

BASE         = os.path.dirname(os.path.abspath(__file__))
HERMES_HOME  = os.path.join(BASE, "hermes-home")
DATA_DIR     = os.path.join(BASE, "data")

# Files to sync (local_path -> repo_path_in_branch)
import glob
BOT_STATE_FILES = [
    (os.path.join(DATA_DIR, "bot_state.json"),        "data/bot_state.json"),
    (os.path.join(DATA_DIR, "trades_history.json"),   "data/trades_history.json"),
    (os.path.join(DATA_DIR, "adaptation_log.json"),   "data/adaptation_log.json"),
]
for pq in glob.glob(os.path.join(DATA_DIR, "*.parquet")):
    BOT_STATE_FILES.append((pq, "data/" + os.path.basename(pq)))

HERMES_STATE_FILES = [
    (os.path.join(HERMES_HOME, "SOUL.md"),            "hermes/SOUL.md"),
    (os.path.join(HERMES_HOME, "USER.md"),            "hermes/USER.md"),
    (os.path.join(HERMES_HOME, "MEMORY.md"),          "hermes/MEMORY.md"),
    (os.path.join(HERMES_HOME, "FULL_HISTORY.md"),    "hermes/FULL_HISTORY.md"),
    (os.path.join(HERMES_HOME, "memories", "user", "ajay_rajbhar.md"),    "hermes/memories/user/ajay_rajbhar.md"),
    (os.path.join(HERMES_HOME, "memories", "memory", "full_history.md"),  "hermes/memories/memory/full_history.md"),
]


#  GitHub API helpers 
class GitHubAPI:
    BASE_URL = "https://api.github.com"

    def __init__(self, token: str, repo: str):
        self.token = token
        self.repo  = repo

    def _req(self, method: str, path: str, data: Optional[dict] = None) -> dict:
        url = f"{self.BASE_URL}{path}"
        body = json.dumps(data).encode() if data else None
        req  = urllib.request.Request(url, data=body, method=method)
        req.add_header("Authorization", f"token {self.token}")
        req.add_header("Accept",        "application/vnd.github.v3+json")
        req.add_header("Content-Type",  "application/json")
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            body_txt = e.read().decode(errors="ignore")
            raise RuntimeError(f"GitHub API {method} {path} -> {e.code}: {body_txt[:300]}")

    def get_file(self, path_in_repo: str, branch: str) -> Optional[dict]:
        """Returns {'sha': ..., 'content': bytes} or None if not found."""
        try:
            r = self._req("GET", f"/repos/{self.repo}/contents/{path_in_repo}?ref={branch}")
            return {
                "sha":     r["sha"],
                "content": base64.b64decode(r["content"].replace("\n", "")),
            }
        except RuntimeError as e:
            if "404" in str(e):
                return None
            raise

    def put_file(self, path_in_repo: str, branch: str,
                 content: bytes, message: str, sha: Optional[str] = None):
        """Create or update a file in the repo."""
        payload = {
            "message": message,
            "content": base64.b64encode(content).decode(),
            "branch":  branch,
        }
        if sha:
            payload["sha"] = sha
        self._req("PUT", f"/repos/{self.repo}/contents/{path_in_repo}", payload)

    def ensure_branch(self, branch: str):
        """Create branch from main if it doesn't exist."""
        try:
            self._req("GET", f"/repos/{self.repo}/git/refs/heads/{branch}")
            return  # already exists
        except RuntimeError:
            pass
        try:
            main = self._req("GET", f"/repos/{self.repo}/git/refs/heads/main")
            sha  = main["object"]["sha"]
            self._req("POST", f"/repos/{self.repo}/git/refs", {
                "ref": f"refs/heads/{branch}",
                "sha": sha,
            })
            print(f"Created branch '{branch}'")
        except Exception as e:
            print(f"Could not create branch '{branch}': {e}")

    def list_branch_files(self, prefix: str, branch: str) -> list[str]:
        """List files under a prefix in the branch."""
        try:
            r = self._req("GET", f"/repos/{self.repo}/contents/{prefix}?ref={branch}")
            if isinstance(r, list):
                return [item["path"] for item in r if item["type"] == "file"]
            return []
        except Exception:
            return []


#  Core sync functions 
def _push_file(api: GitHubAPI, local_path: str, repo_path: str, branch: str, label: str = ""):
    """Push one local file to GitHub, skip if unchanged."""
    if not os.path.exists(local_path):
        return False
    try:
        with open(local_path, "rb") as f:
            local_bytes = f.read()
        # Redact any tokens from text files
        if local_path.endswith((".md", ".txt", ".json", ".yaml", ".yml")):
            text = local_bytes.decode("utf-8", errors="ignore")
            text = re.sub(r'hf_[A-Za-z0-9]{30,}', '[REDACTED]', text)
            text = re.sub(r'ghp_[A-Za-z0-9]{30,}', '[REDACTED]', text)
            local_bytes = text.encode("utf-8")
        existing = api.get_file(repo_path, branch)
        if existing and existing["content"] == local_bytes:
            return False  # unchanged
        sha = existing["sha"] if existing else None
        api.put_file(repo_path, branch, local_bytes,
                     f"sync: {label or repo_path}", sha)
        return True
    except Exception as e:
        print(f"   push {repo_path}: {e}")
        return False


def _pull_file(api: GitHubAPI, repo_path: str, local_path: str, branch: str):
    """Pull one file from GitHub to local disk."""
    existing = api.get_file(repo_path, branch)
    if not existing:
        return False
    try:
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        with open(local_path, "wb") as f:
            f.write(existing["content"])
        return True
    except Exception as e:
        print(f"   pull {repo_path}: {e}")
        return False


def _push_db(api: GitHubAPI, db_path: str, repo_path: str, branch: str):
    """Push a SQLite DB safely (via backup snapshot)."""
    if not os.path.exists(db_path):
        return False
    tmp = os.path.join(tempfile.gettempdir(), f"_snap_{os.path.basename(db_path)}")
    try:
        src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        dst = sqlite3.connect(tmp)
        src.backup(dst)
        dst.close(); src.close()
        upload_path = tmp
    except Exception:
        upload_path = db_path  # fallback: read live file
    try:
        with open(upload_path, "rb") as f:
            data = f.read()
        existing = api.get_file(repo_path, branch)
        sha = existing["sha"] if existing else None
        api.put_file(repo_path, branch, data,
                     f"sync: {os.path.basename(db_path)}", sha)
        return True
    except Exception as e:
        print(f"   push db {repo_path}: {e}")
        return False
    finally:
        try: os.remove(tmp)
        except Exception: pass


#  Public commands 
def push():
    if not GITHUB_TOKEN:
        print("no GITHUB_TOKEN; skip push"); return
    api = GitHubAPI(GITHUB_TOKEN, GITHUB_REPO)
    api.ensure_branch(STATE_BRANCH)
    n = 0
    for local, remote in BOT_STATE_FILES:
        if _push_file(api, local, remote, STATE_BRANCH, "bot-state"):
            n += 1
            print(f"  OK pushed {remote}")
    print(f"push done ({n} files updated)")


def pull():
    '''Pull bot state from GitHub.'''
    if not GITHUB_TOKEN:
        print("no GITHUB_TOKEN; skip pull"); return
    api = GitHubAPI(GITHUB_TOKEN, GITHUB_REPO)
    n = 0
    for local, remote in BOT_STATE_FILES:
        if _pull_file(api, remote, local, STATE_BRANCH):
            n += 1
            print(f"  OK pulled {remote}")
    
    # Dynamically pull all parquet files from data/ directory on remote
    for repo_path in api.list_branch_files("data", STATE_BRANCH):
        if repo_path.endswith(".parquet"):
            local_path = os.path.join(DATA_DIR, os.path.basename(repo_path))
            if _pull_file(api, repo_path, local_path, STATE_BRANCH):
                n += 1
                print(f"  OK pulled {repo_path}")
                
    print(f"pull done ({n} files restored)")


def push_hermes():
    """Push Hermes memory + DBs to GitHub bot-state branch."""
    if not GITHUB_TOKEN:
        print("no GITHUB_TOKEN; skip push-hermes"); return
    api = GitHubAPI(GITHUB_TOKEN, GITHUB_REPO)
    api.ensure_branch(STATE_BRANCH)
    n = 0

    # Text memory files
    for local, remote in HERMES_STATE_FILES:
        if _push_file(api, local, remote, STATE_BRANCH, "hermes-mem"):
            n += 1
            print(f"  OK pushed {remote}")

    # Bot state JSON files
    for local, remote in BOT_STATE_FILES:
        if _push_file(api, local, remote, STATE_BRANCH, "bot-state"):
            n += 1
            print(f"  OK pushed {remote}")

    # SQLite DBs from hermes-home and mnemosyne
    db_dirs = [HERMES_HOME, os.path.join(HERMES_HOME, "mnemosyne")]
    for db_dir in db_dirs:
        if not os.path.isdir(db_dir):
            continue
        for fname in os.listdir(db_dir):
            if fname.endswith(".db") and os.path.isfile(os.path.join(db_dir, fname)):
                if _push_db(api, os.path.join(db_dir, fname),
                            f"hermes/db/{fname}", STATE_BRANCH):
                    n += 1
                    print(f"  OK pushed db {fname}")

    # Cron jobs
    cron_dir = os.path.join(HERMES_HOME, "cron")
    if os.path.isdir(cron_dir):
        for fname in os.listdir(cron_dir):
            fp = os.path.join(cron_dir, fname)
            if os.path.isfile(fp):
                if _push_file(api, fp, f"hermes/cron/{fname}", STATE_BRANCH):
                    n += 1

    # Sessions (Chat History), Skills, and Dynamic Memories
    for dname in ["sessions", "skills", "memories", "logs"]:
        dir_path = os.path.join(HERMES_HOME, dname)
        if os.path.isdir(dir_path):
            for root, _, files in os.walk(dir_path):
                for fname in files:
                    if not fname.endswith(".lock"):
                        fp = os.path.join(root, fname)
                        rel_path = os.path.relpath(fp, HERMES_HOME).replace("\\", "/")
                        if _push_file(api, fp, f"hermes/{rel_path}", STATE_BRANCH):
                            n += 1

    print(f"push-hermes done ({n} files updated)")


def pull_hermes():
    """Pull Hermes memory + DBs from GitHub bot-state branch."""
    if not GITHUB_TOKEN:
        print("no GITHUB_TOKEN; skip pull-hermes"); return
    api = GitHubAPI(GITHUB_TOKEN, GITHUB_REPO)
    n = 0

    os.makedirs(HERMES_HOME, exist_ok=True)
    os.makedirs(os.path.join(HERMES_HOME, "mnemosyne"), exist_ok=True)

    # Text memory files
    for local, remote in HERMES_STATE_FILES:
        if _pull_file(api, remote, local, STATE_BRANCH):
            n += 1
            print(f"  OK pulled {remote}")

    # Bot state JSON files
    for local, remote in BOT_STATE_FILES:
        if _pull_file(api, remote, local, STATE_BRANCH):
            n += 1
            print(f"  OK pulled {remote}")

    # SQLite DBs
    for repo_path in api.list_branch_files("hermes/db", STATE_BRANCH):
        fname = os.path.basename(repo_path)
        for dest_dir in [HERMES_HOME, os.path.join(HERMES_HOME, "mnemosyne")]:
            local_path = os.path.join(dest_dir, fname)
            if not os.path.exists(local_path):  # don't overwrite live DB
                _pull_file(api, repo_path, local_path, STATE_BRANCH)
        n += 1

    # Cron jobs
    cron_dir = os.path.join(HERMES_HOME, "cron")
    os.makedirs(cron_dir, exist_ok=True)
    for repo_path in api.list_branch_files("hermes/cron", STATE_BRANCH):
        fname = os.path.basename(repo_path)
        local_path = os.path.join(cron_dir, fname)
        if not os.path.exists(local_path):
            if _pull_file(api, repo_path, local_path, STATE_BRANCH):
                n += 1

    # Sessions, Skills, and Dynamic Memories
    for dname in ["sessions", "skills", "memories", "logs"]:
        for repo_path in api.list_branch_files(f"hermes/{dname}", STATE_BRANCH):
            rel_path = repo_path.removeprefix("hermes/")
            local_path = os.path.join(HERMES_HOME, rel_path.replace("/", os.sep))
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            if not os.path.exists(local_path):
                if _pull_file(api, repo_path, local_path, STATE_BRANCH):
                    n += 1

    print(f"pull-hermes done ({n} files restored)")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "pull"
    if   mode == "push":          push()
    elif mode == "pull":          pull()
    elif mode == "push-hermes":   push_hermes()
    elif mode == "pull-hermes":   pull_hermes()
    else:
        print(f"Unknown mode: {mode}")
        sys.exit(1)
