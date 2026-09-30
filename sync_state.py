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


def safe_snapshot_db(db_path, tmp_dst):
    try:
        import sqlite3
        src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        dst = sqlite3.connect(tmp_dst)
        src.backup(dst)
        dst.close()
        src.close()
        return True
    except Exception:
        try:
            shutil.copy2(db_path, tmp_dst)
            return True
        except Exception:
            return False


def push_hermes():
    """Push hermes-home state (mnemosyne DBs, state.db, MEMORY.md, SOUL.md, USER.md) to HF."""
    if not TOKEN:
        print("no HF_TOKEN; skip"); return
    import re, tempfile
    from huggingface_hub import HfApi
    api = HfApi(token=TOKEN)
    api.create_repo(REPO, repo_type="dataset", private=True, exist_ok=True)
    os.makedirs(HERMES_HOME, exist_ok=True)
    os.makedirs(HERMES_MNEMO, exist_ok=True)
    n = 0

    seen_files = set()
    for root_dir in [HERMES_HOME, HERMES_MNEMO, os.path.join(BASE, "HERMES_MEMORY")]:
        if not os.path.isdir(root_dir):
            continue
        for f in os.listdir(root_dir):
            full_path = os.path.join(root_dir, f)
            if os.path.isfile(full_path):
                if f.endswith(".db"):
                    key = ("db", f)
                    if key not in seen_files:
                        seen_files.add(key)
                        tmp_copy = os.path.join(tempfile.gettempdir(), "_snap_%s" % f)
                        upload_src = tmp_copy if safe_snapshot_db(full_path, tmp_copy) else full_path
                        try:
                            api.upload_file(
                                path_or_fileobj=upload_src,
                                path_in_repo="hermes-mnemosyne/%s" % f,
                                repo_id=REPO, repo_type="dataset")
                            n += 1
                        except Exception as e:
                            print("Error uploading DB %s: %s" % (f, e))
                        finally:
                            if os.path.exists(tmp_copy):
                                try: os.remove(tmp_copy)
                                except Exception: pass
                elif f.endswith(".md"):
                    key = ("md", f)
                    if key not in seen_files:
                        seen_files.add(key)
                        try:
                            with open(full_path, "r", encoding="utf-8", errors="ignore") as mdf:
                                content = mdf.read()
                            sanitized = re.sub(r'hf_[A-Za-z0-9]{30,}', '[REDACTED_HF_TOKEN]', content)
                            api.upload_file(
                                path_or_fileobj=sanitized.encode("utf-8"),
                                path_in_repo="hermes-mnemosyne/%s" % f,
                                repo_id=REPO, repo_type="dataset")
                            n += 1
                        except Exception as e:
                            print("Error uploading %s: %s" % (f, e))

    print("push-hermes done (%d files)" % n)


def pull_hermes():
    """Pull hermes mnemosyne DBs and memory markdown files from HF into hermes-home."""
    if not TOKEN:
        print("no HF_TOKEN; skip"); return
    from huggingface_hub import HfApi, hf_hub_download
    api = HfApi(token=TOKEN)
    try:
        files = api.list_repo_files(REPO, repo_type="dataset")
    except Exception as e:
        print("pull error or state repo empty: %s" % e)
        return
    n = 0
    os.makedirs(HERMES_HOME, exist_ok=True)
    os.makedirs(HERMES_MNEMO, exist_ok=True)
    for f in files:
        if f.startswith("hermes-mnemosyne/"):
            fname = os.path.basename(f)
            if not fname:
                continue
            try:
                p = hf_hub_download(REPO, f, repo_type="dataset", token=TOKEN)
                if fname == "mnemosyne.db":
                    for d in [HERMES_HOME, HERMES_MNEMO]:
                        try: shutil.copy(p, os.path.join(d, "mnemosyne.db"))
                        except (PermissionError, OSError): pass
                elif fname.endswith(".db"):
                    for d in [HERMES_HOME, HERMES_MNEMO]:
                        try: shutil.copy(p, os.path.join(d, fname))
                        except (PermissionError, OSError): pass
                elif fname.endswith(".md"):
                    try: shutil.copy(p, os.path.join(HERMES_HOME, fname))
                    except (PermissionError, OSError): pass
                    if fname == "FULL_HISTORY.md":
                        os.makedirs(os.path.join(BASE, "HERMES_MEMORY"), exist_ok=True)
                        try: shutil.copy(p, os.path.join(BASE, "HERMES_MEMORY", "FULL_HISTORY.md"))
                        except (PermissionError, OSError): pass
                        os.makedirs(os.path.join(HERMES_HOME, "HERMES_MEMORY"), exist_ok=True)
                        try: shutil.copy(p, os.path.join(HERMES_HOME, "HERMES_MEMORY", "FULL_HISTORY.md"))
                        except (PermissionError, OSError): pass
                n += 1
            except Exception as e:
                print("Error downloading %s: %s" % (f, e))
    print("pull-hermes done (%d files)" % n)


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
