# utils/system.py
import os
import subprocess
import sys
from pathlib import Path

def get_data_dir():
    """Возвращает папку для хранения данных приложения."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home()))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    data_dir = base / "SingularityEngine"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir

def hidden_startupinfo():
    if sys.platform == "win32":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = subprocess.SW_HIDE
        return si
    return None


def open_path(path):
    if sys.platform == "win32":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def find_tool_in_path(name):
    import shutil
    path = shutil.which(name)
    if path:
        return path

    if sys.platform == "win32":
        program_files = os.environ.get("ProgramFiles", "C:\\Program Files")
        program_files_x86 = os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")
        local_app_data = os.environ.get("LOCALAPPDATA", "")

        search_paths = {
            "git": [
                Path(program_files) / "Git/bin/git.exe",
                Path(program_files) / "Git/cmd/git.exe",
                Path(program_files_x86) / "Git/bin/git.exe",
                Path(program_files_x86) / "Git/cmd/git.exe",
                Path(local_app_data) / "Programs/Git/bin/git.exe",
                Path(local_app_data) / "Programs/Git/cmd/git.exe",
                Path("C:/Git/bin/git.exe"),
                Path("C:/Git/cmd/git.exe"),
            ],
            "python": [
                Path(program_files) / "Python314/python.exe",
                Path(program_files_x86) / "Python314/python.exe",
                Path(local_app_data) / "Programs/Python/Python314/python.exe",
            ],
            "dotnet": [
                Path(program_files) / "dotnet/dotnet.exe",
                Path(program_files_x86) / "dotnet/dotnet.exe",
                Path("C:/Program Files/dotnet/dotnet.exe"),
            ]
        }
        for p in search_paths.get(name, []):
            if p.exists():
                return str(p)

        try:
            res = subprocess.run(
                ["cmd", "/c", "where", name],
                capture_output=True, text=True, timeout=5,
                startupinfo=hidden_startupinfo(),
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip().split('\n')[0]
        except Exception:
            pass

    return None