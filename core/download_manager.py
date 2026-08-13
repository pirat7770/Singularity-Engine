import os
import time
import urllib.request
from pathlib import Path


class DownloadManager:
    def __init__(self, cache_dir=None):
        if cache_dir is None:
            cache_dir = Path(os.environ.get("TEMP", Path.cwd())) / "singularity_engine"
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def download(self, url, dest_name=None, progress_callback=None, retries=3):
        """Скачивает файл с кэшированием и повторными попытками."""
        if dest_name is None:
            dest_name = url.split("/")[-1]

        dest_path = self.cache_dir / dest_name
        if dest_path.exists():
            return dest_path

        for attempt in range(1, retries + 1):
            try:
                if progress_callback:
                    urllib.request.urlretrieve(url, str(dest_path), progress_callback)
                else:
                    urllib.request.urlretrieve(url, str(dest_path))
                return dest_path
            except Exception:
                if attempt == retries:
                    raise
                time.sleep(2)

        return None