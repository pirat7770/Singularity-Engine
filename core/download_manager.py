import os
import time
import hashlib
import urllib.request
from pathlib import Path


class DownloadCancelled(Exception):
    """Исключение, которое выбрасывается при отмене загрузки."""
    pass


class DownloadIntegrityError(Exception):
    """Выбрасывается, когда хеш скачанного файла не совпадает с ожидаемым."""
    pass


class DownloadManager:
    def __init__(self, cache_dir=None):
        if cache_dir is None:
            from utils.system import get_data_dir
            cache_dir = get_data_dir() / "download_cache"
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def download(self, url, dest_name=None, progress_callback=None,
                 retries=3, cancel_event=None, expected_sha256=None):
        """
        Скачивает файл с кэшированием, повторными попытками, отменой и проверкой SHA-256.

        :param url: URL файла
        :param dest_name: имя файла в кэше (если None, берётся из URL)
        :param progress_callback: функция(block_num, block_size, total_size) для отображения прогресса
        :param retries: количество попыток
        :param cancel_event: threading.Event для отмены загрузки
        :param expected_sha256: ожидаемый SHA-256 хеш (hex, без пробелов). Если None, проверка не выполняется.
        :return: Path к скачанному файлу
        """
        if dest_name is None:
            dest_name = url.split("/")[-1]

        dest_path = self.cache_dir / dest_name

        # Если файл уже есть в кэше, и хеш не задан – возвращаем без проверки.
        # Если хеш задан, проверяем существующий файл, чтобы не перекачивать.
        if dest_path.exists():
            if expected_sha256 is None:
                return dest_path
            actual = self._calc_sha256(dest_path)
            if actual == expected_sha256.lower():
                return dest_path
            else:
                # Файл повреждён – удаляем и качаем заново
                try:
                    dest_path.unlink()
                except OSError:
                    pass

        for attempt in range(1, retries + 1):
            try:
                # Удаляем недокачанный файл перед новой попыткой
                if dest_path.exists():
                    try:
                        dest_path.unlink()
                    except OSError:
                        pass

                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=30) as response:
                    total_size = int(response.headers.get('Content-Length', 0))
                    downloaded = 0
                    block_size = 8192

                    with open(dest_path, 'wb') as f:
                        while True:
                            if cancel_event and cancel_event.is_set():
                                raise DownloadCancelled("Загрузка отменена пользователем")
                            chunk = response.read(block_size)
                            if not chunk:
                                break
                            f.write(chunk)
                            downloaded += len(chunk)

                            if progress_callback and total_size > 0:
                                block_num = downloaded // block_size
                                progress_callback(block_num, block_size, total_size)

                    if total_size > 0 and downloaded < total_size * 0.9:
                        raise Exception(f"Загрузка не завершена: получено {downloaded} из {total_size} байт")

                # Проверка хеша после загрузки
                if expected_sha256 is not None:
                    actual = self._calc_sha256(dest_path)
                    if actual != expected_sha256.lower():
                        # Хеш не совпал – удаляем файл и бросаем исключение
                        try:
                            dest_path.unlink()
                        except OSError:
                            pass
                        raise DownloadIntegrityError(
                            f"Хеш скачанного файла {actual} не совпадает с ожидаемым {expected_sha256}"
                        )

                return dest_path

            except DownloadCancelled:
                raise
            except DownloadIntegrityError:
                raise  # не повторяем при несовпадении хеша
            except Exception as e:
                if attempt == retries:
                    raise
                delay = 2 ** attempt
                if cancel_event and cancel_event.wait(delay):
                    raise DownloadCancelled("Загрузка отменена пользователем")
                if not (cancel_event and cancel_event.is_set()):
                    time.sleep(delay)

        return None

    def _calc_sha256(self, file_path):
        sha256 = hashlib.sha256()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(65536), b''):
                sha256.update(chunk)
        return sha256.hexdigest()