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
import glob
FILES = [
    (os.path.join(BASE, "data", "bot_state.json"), "bot_state.json"),
    (os.path.join(BASE, "data", "trades_history.json"), "trades_history.json"),
]
for pq in glob.glob(os.path.join(BASE, "data", "*.parquet")):
    FILES.append((pq, "data/" + os.path.basename(pq)))
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
    
    # Download hardcoded FILES
    for path, name in FILES:
        if name in files:
            p = hf_hub_download(REPO, name, repo_type="dataset", token=TOKEN)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            shutil.copy(p, path)
            
    # Download any parquet files stored in data/ on remote
    for f in files:
        if f.startswith("data/") and f.endswith(".parquet"):
            p = hf_hub_download(REPO, f, repo_type="dataset", token=TOKEN)
            local_path = os.path.join(BASE, "data", os.path.basename(f))
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            shutil.copy(p, local_path)
            
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

    # 3. Upload native Hermes memories/user and memories/memory
    mem_base = os.path.join(HERMES_HOME, "memories")
    if os.path.isdir(mem_base):
        for sub in ["user", "memory"]:
            s_dir = os.path.join(mem_base, sub)
            if os.path.isdir(s_dir):
                for mf in os.listdir(s_dir):
                    mf_path = os.path.join(s_dir, mf)
                    if os.path.isfile(mf_path) and (mf.endswith(".md") or mf.endswith(".txt")):
                        try:
                            with open(mf_path, "r", encoding="utf-8", errors="ignore") as f:
                                mem_text = re.sub(r'hf_[A-Za-z0-9]{30,}', '[REDACTED_HF_TOKEN]', f.read())
                            api.upload_file(
                                path_or_fileobj=mem_text.encode("utf-8"),
                                path_in_repo="hermes-memories/%s/%s" % (sub, mf),
                                repo_id=REPO, repo_type="dataset")
                            n += 1
                        except Exception as e:
                            print("Error uploading memory %s/%s: %s" % (sub, mf, e))

    # 4. Upload skills directory (fast diff upload via upload_folder)
    skills_base = os.path.join(HERMES_HOME, "skills")
    if os.path.isdir(skills_base):
        try:
            api.upload_folder(
                folder_path=skills_base,
                path_in_repo="hermes-skills",
                repo_id=REPO,
                repo_type="dataset",
                commit_message="Sync hermes skills"
            )
            n += 1
        except Exception as e:
            print("Error uploading skills folder: %s" % e)

    # 5. Upload cron directory (cron schedules, jobs.json)
    cron_base = os.path.join(HERMES_HOME, "cron")
    if os.path.isdir(cron_base) and os.listdir(cron_base):
        try:
            api.upload_folder(
                folder_path=cron_base,
                path_in_repo="hermes-cron",
                repo_id=REPO,
                repo_type="dataset",
                commit_message="Sync hermes cron jobs"
            )
            n += 1
        except Exception as e:
            print("Error uploading cron folder: %s" % e)

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
    mem_user = os.path.join(HERMES_HOME, "memories", "user")
    mem_note = os.path.join(HERMES_HOME, "memories", "memory")
    os.makedirs(mem_user, exist_ok=True)
    os.makedirs(mem_note, exist_ok=True)

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

        elif f.startswith("hermes-memories/"):
            # Native Hermes memory file
            parts = f.split("/")
            if len(parts) >= 3:
                sub = parts[1] # 'user' or 'memory'
                fname = parts[2]
                target_dir = os.path.join(HERMES_HOME, "memories", sub)
                os.makedirs(target_dir, exist_ok=True)
                try:
                    p = hf_hub_download(REPO, f, repo_type="dataset", token=TOKEN)
                    shutil.copy(p, os.path.join(target_dir, fname))
                    n += 1
                except Exception as e:
                    print("Error downloading native memory %s: %s" % (f, e))
        elif f.startswith("hermes-skills/"):
            rel_path = f[len("hermes-skills/"):]
            target_path = os.path.join(HERMES_HOME, "skills", rel_path)
            if not os.path.exists(target_path):
                os.makedirs(os.path.dirname(target_path), exist_ok=True)
                try:
                    p = hf_hub_download(REPO, f, repo_type="dataset", token=TOKEN)
                    shutil.copy(p, target_path)
                    n += 1
                except Exception as e:
                    print("Error downloading skill %s: %s" % (rel_path, e))

        elif f.startswith("hermes-cron/"):
            rel_path = f[len("hermes-cron/"):]
            target_path = os.path.join(HERMES_HOME, "cron", rel_path)
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            try:
                p = hf_hub_download(REPO, f, repo_type="dataset", token=TOKEN)
                shutil.copy(p, target_path)
                n += 1
            except Exception as e:
                print("Error downloading cron %s: %s" % (rel_path, e))

    # Fallback seeding if native memories are empty
    if not os.listdir(mem_user) and os.path.exists(os.path.join(HERMES_HOME, "USER.md")):
        shutil.copy(os.path.join(HERMES_HOME, "USER.md"), os.path.join(mem_user, "ajay_rajbhar.md"))
    if not os.listdir(mem_note) and os.path.exists(os.path.join(HERMES_HOME, "FULL_HISTORY.md")):
        shutil.copy(os.path.join(HERMES_HOME, "FULL_HISTORY.md"), os.path.join(mem_note, "full_history.md"))

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

