"""Sync AjayBot state + memory to private HF dataset repo (survives Render restarts).
Usage: python sync_state.py push | pull"""
import os
import sys
import shutil

TOKEN = os.environ.get("HF_TOKEN", "")
REPO = os.environ.get("HF_STATE_REPO", "rareember/ajaybot-state")
BASE = os.path.dirname(os.path.abspath(__file__))
HERMES_HOME = os.path.join(BASE, "hermes-home")
HERMES_MNEMO = os.path.join(HERMES_HOME, "mnemosyne")
FILES = [
    (os.path.join(BASE, "data", "bot_state.json"), "bot_state.json"),
    (os.path.join(BASE, "data", "trades_history.json"), "trades_history.json"),
]
MNEMO_DIR = os.environ.get("MNEMOSYNE_DATA_DIR", os.path.join(BASE, "mnemosyne_data"))


def push():
    if not TOKEN:
        print("no HF_TOKEN; skip"); return
    from huggingface_hub import HfApi
    api = HfApi(token=TOKEN)
    api.create_repo(REPO, repo_type="dataset", private=True, exist_ok=True)
    for path, name in FILES:
        if os.path.exists(path):
            api.upload_file(path_or_fileobj=path, path_in_repo=name,
                            repo_id=REPO, repo_type="dataset")
    if os.path.isdir(MNEMO_DIR):
        for f in os.listdir(MNEMO_DIR):
            if f.endswith(".db"):
                api.upload_file(path_or_fileobj=os.path.join(MNEMO_DIR, f),
                                path_in_repo=f"mnemosyne/{f}",
                                repo_id=REPO, repo_type="dataset")
    print("push done")


def pull():
    if not TOKEN:
        print("no HF_TOKEN; skip"); return
    try:
        from huggingface_hub import HfApi, hf_hub_download
        api = HfApi(token=TOKEN)
        files = api.list_repo_files(REPO, repo_type="dataset")
    except Exception:
        print("state repo empty/new"); return
    for path, name in FILES:
        if name in files:
            p = hf_hub_download(REPO, name, repo_type="dataset", token=TOKEN)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            shutil.copy(p, path)
    for f in files:
        if f.startswith("mnemosyne/") and f.endswith(".db"):
            p = hf_hub_download(REPO, f, repo_type="dataset", token=TOKEN)
            os.makedirs(MNEMO_DIR, exist_ok=True)
            shutil.copy(p, os.path.join(MNEMO_DIR, os.path.basename(f)))
    print("pull done")


def push_hermes():
    """Push hermes-home/mnemosyne DBs to HF (no secrets, DBs only)."""
    if not TOKEN:
        print("no HF_TOKEN; skip"); return
    from huggingface_hub import HfApi
    api = HfApi(token=TOKEN)
    api.create_repo(REPO, repo_type="dataset", private=True, exist_ok=True)
    os.makedirs(HERMES_MNEMO, exist_ok=True)
    n = 0
    if os.path.isdir(HERMES_MNEMO):
        for f in os.listdir(HERMES_MNEMO):
            if f.endswith(".db"):
                api.upload_file(
                    path_or_fileobj=os.path.join(HERMES_MNEMO, f),
                    path_in_repo="hermes-mnemosyne/%s" % f,
                    repo_id=REPO, repo_type="dataset")
                n += 1
    print("push-hermes done (%d dbs)" % n)


def pull_hermes():
    """Pull hermes mnemosyne DBs from HF into hermes-home."""
    if not TOKEN:
        print("no HF_TOKEN; skip"); return
    try:
        from huggingface_hub import HfApi, hf_hub_download
        api = HfApi(token=TOKEN)
        files = api.list_repo_files(REPO, repo_type="dataset")
    except Exception:
        print("state repo empty/new"); return
    n = 0
    for f in files:
        if f.startswith("hermes-mnemosyne/") and f.endswith(".db"):
            p = hf_hub_download(REPO, f, repo_type="dataset", token=TOKEN)
            os.makedirs(HERMES_MNEMO, exist_ok=True)
            shutil.copy(p, os.path.join(HERMES_MNEMO, os.path.basename(f)))
            n += 1
    print("pull-hermes done (%d dbs)" % n)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "pull"
    if mode == "push":
        push()
    elif mode == "pull":
        pull()
    elif mode == "push-hermes":
        push_hermes()
    elif mode == "pull-hermes":
        pull_hermes()
    else:
        pull()
