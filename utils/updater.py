# utils/updater.py
import json
import urllib.request

GITHUB_REPO = "pirat7770/Singularity-Engine"

def get_latest_release():
    """Возвращает tag_name последнего релиза (включая pre-release)."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases?per_page=1"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
            if data:
                return data[0].get("tag_name")
    except Exception:
        pass
    return None


def get_latest_release_asset():
    """
    Возвращает (tag_name, asset_url, asset_type) для последнего релиза.
    asset_type: 'exe' или 'zip'. Если ассет не найден, возвращает (tag_name, None, None).
    """
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases?per_page=1"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
            if not data:
                return None, None, None
            release = data[0]
            tag = release.get("tag_name")
            assets = release.get("assets", [])
            for asset in assets:
                name = asset.get("name", "")
                if name.endswith(".exe"):
                    return tag, asset.get("browser_download_url"), "exe"
                elif name.endswith(".zip"):
                    return tag, asset.get("browser_download_url"), "zip"
            return tag, None, None
    except Exception:
        pass
    return None, None, None