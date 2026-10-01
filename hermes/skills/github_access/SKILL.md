# GitHub Access Skill for Radha (Hermes Agent)

## What this skill does
Gives Radha direct GitHub API access to read, create, and modify files in the `nothing12837-lang/ajaybot` repo — without needing a laptop.

## When to use
- Ajay asks Radha to "fix this code", "update that file", "check GitHub Actions"
- Radha needs to create a workflow, update bot config, or push any code change
- Checking latest workflow run status
- Reading file contents from the repo

## Auth
`GITHUB_TOKEN` environment variable is available in Render and GitHub Actions. Use it for all API calls. Never print it.

## Repo
- **Repo:** `nothing12837-lang/ajaybot`
- **Main branch:** `main`
- **State branch:** `bot-state`

---

## HOW TO READ A FILE FROM GITHUB

```python
import urllib.request, json, base64, os

def github_get_file(path: str, branch: str = "main") -> str:
    token = os.environ["GITHUB_TOKEN"]
    url = f"https://api.github.com/repos/nothing12837-lang/ajaybot/contents/{path}?ref={branch}"
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"token {token}")
    req.add_header("Accept", "application/vnd.github.v3+json")
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read())
    return base64.b64decode(data["content"].replace("\n","")).decode("utf-8")

# Example: read the bot config
content = github_get_file("config/config.yaml")
print(content)
```

---

## HOW TO WRITE / UPDATE A FILE ON GITHUB

```python
import urllib.request, json, base64, os

def github_put_file(path: str, content: str, message: str, branch: str = "main"):
    token = os.environ["GITHUB_TOKEN"]
    repo  = "nothing12837-lang/ajaybot"
    # Get current SHA (required for updates)
    url = f"https://api.github.com/repos/{repo}/contents/{path}?ref={branch}"
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"token {token}")
    req.add_header("Accept", "application/vnd.github.v3+json")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            sha = json.loads(r.read())["sha"]
    except Exception:
        sha = None  # new file
    payload = {
        "message": message,
        "content": base64.b64encode(content.encode()).decode(),
        "branch":  branch,
    }
    if sha:
        payload["sha"] = sha
    body = json.dumps(payload).encode()
    req2 = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/contents/{path}",
        data=body, method="PUT"
    )
    req2.add_header("Authorization", f"token {token}")
    req2.add_header("Content-Type", "application/json")
    req2.add_header("Accept", "application/vnd.github.v3+json")
    with urllib.request.urlopen(req2, timeout=15) as r:
        result = json.loads(r.read())
    print(f"✅ Pushed {path} → {result['commit']['sha'][:7]}")
    return result

# Example: update bot config symbol list
new_config = github_get_file("config/config.yaml")
new_config = new_config.replace("leverage: 20", "leverage: 25")
github_put_file("config/config.yaml", new_config, "Update leverage to 25x via Radha")
```

---

## HOW TO CHECK GITHUB ACTIONS STATUS

```python
import urllib.request, json, os
from datetime import datetime, timezone

def check_workflow_status(workflow_file: str) -> dict:
    token = os.environ["GITHUB_TOKEN"]
    url = f"https://api.github.com/repos/nothing12837-lang/ajaybot/actions/workflows/{workflow_file}/runs?per_page=1"
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"token {token}")
    req.add_header("Accept", "application/vnd.github.v3+json")
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read())
    if not data["workflow_runs"]:
        return {"status": "never_run"}
    run = data["workflow_runs"][0]
    created = run["created_at"]  # ISO string
    return {
        "name":       run["name"],
        "status":     run["status"],       # queued/in_progress/completed
        "conclusion": run["conclusion"],   # success/failure/skipped/None
        "created_at": created,
        "url":        run["html_url"],
    }

# Check all key workflows
for wf in ["ajaybot-paper.yml", "ajaybot-monitor.yml", "keep-alive.yml", "bot-24x7.yml"]:
    info = check_workflow_status(wf)
    print(f"{wf}: {info['conclusion'] or info['status']} @ {info.get('created_at','?')}")
```

---

## HOW TO TRIGGER A WORKFLOW (workflow_dispatch)

```python
import urllib.request, json, os

def trigger_workflow(workflow_file: str, branch: str = "main"):
    token = os.environ["GITHUB_TOKEN"]
    url = f"https://api.github.com/repos/nothing12837-lang/ajaybot/actions/workflows/{workflow_file}/dispatches"
    payload = json.dumps({"ref": branch}).encode()
    req = urllib.request.Request(url, data=payload, method="POST")
    req.add_header("Authorization", f"token {token}")
    req.add_header("Accept", "application/vnd.github.v3+json")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=15) as r:
        pass  # 204 No Content on success
    print(f"✅ Triggered {workflow_file}")

# Re-trigger paper trading cycle manually
trigger_workflow("ajaybot-paper.yml")
```

---

## IMPORTANT RULES
1. Never expose `GITHUB_TOKEN` value in any message to Ajay
2. Always use `message` parameter that explains what changed
3. Only push to `main` branch unless explicitly told otherwise  
4. For the `bot-state` branch — that's read/write for state sync only
5. If a push fails with 409 Conflict: fetch fresh SHA and retry once
