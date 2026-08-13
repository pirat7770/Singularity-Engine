# utils/updater.py
import json
import urllib.request

GITHUB_REPO = "pirat7770/Singularity-Engine"

def get_latest_release():
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases?per_page=1"
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            data = json.loads(response.read().decode())
            if data:
                return data[0].get("tag_name")
    except Exception:
        pass
    return None