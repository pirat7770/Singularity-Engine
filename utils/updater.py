# utils/updater.py
import json
import urllib.request

GITHUB_REPO = "your_username/your_repo"  # замените на ваш репозиторий

def get_latest_release():
    """Возвращает tag_name последнего релиза с GitHub."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            data = json.loads(response.read().decode())
            return data.get("tag_name")
    except Exception:
        return None