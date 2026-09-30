#!/usr/bin/env python3
import os
import sys
from pathlib import Path
from huggingface_hub import HfApi

# Check environment first, fallback to .env if present
env_path = Path('/opt/render/project/src/hermes-home/.env')
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            if line.startswith('HF_TOKEN='):
                os.environ['HF_TOKEN'] = line.strip().split('=', 1)[1]
                break

HF_TOKEN = os.environ.get('HF_TOKEN')
HF_REPO = os.environ.get('HF_STATE_REPO', 'rareember/ajaybot-state')


def main():
    if not HF_TOKEN:
        print("ERROR: HF_TOKEN not set")
        sys.exit(1)

    api = HfApi(token=HF_TOKEN)

    try:
        files = api.list_repo_files(repo_id=HF_REPO, repo_type='dataset')
        print(f"Files in {HF_REPO}: {len(files)} files found")

        if 'bot_state.json' in files:
            print("✅ bot_state.json exists on HF")
        else:
            print("⚠️ bot_state.json NOT found on HF")

        if 'trades_history.json' in files:
            print("✅ trades_history.json exists on HF")
        else:
            print("⚠️ trades_history.json NOT found on HF")

    except Exception as e:
        print(f"Failed to check HF repo: {e}")
        sys.exit(1)

    print(f"✅ Bot state sync check complete for {HF_REPO}")


if __name__ == '__main__':
    main()
