# ui/mixins/system_mixin.py
import os
import sys
import time
import json
import platform
import re
import subprocess
import threading
import ctypes
from pathlib import Path
from tkinter import messagebox

try:
    import winreg
    WINREG_AVAILABLE = True
except ImportError:
    winreg = None
    WINREG_AVAILABLE = False

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    psutil = None
    PSUTIL_AVAILABLE = False

from utils.system import (
    hidden_startupinfo as sys_hidden_startupinfo,
    open_path as sys_open_path,
    find_tool_in_path as sys_find_tool,
)


class SystemMixin:
    """Системные методы: работа с процессами, проверка инструментов, очистка кэшей, уведомления."""

    def _is_admin(self):
        """Проверяет, запущена ли программа с правами администратора."""
        if sys.platform == "win32":
            try:
                return ctypes.windll.shell32.IsUserAnAdmin()
            except Exception:
                return False
        return True

    # ================== Скрытие консоли и запуск процессов ==================

    def _hidden_startupinfo(self):
        """Возвращает startupinfo для скрытия консольного окна (Windows)."""
        return sys_hidden_startupinfo()

    def _run_subprocess(self, cmd, cwd, step_name, progress_parser=None, operation_name=None):
        """
        Запускает процесс с скрытой консолью, транслирует вывод в лог,
        поддерживает отмену через _cancel_download и _download_cancel_event.
        """
        self.log(f"🔧 Выполнение: {step_name}", tag="operation")
        try:
            creationflags = 0
            if sys.platform == "win32":
                # CREATE_NO_WINDOW для полного скрытия консоли
                creationflags = subprocess.CREATE_NO_WINDOW
            process = subprocess.Popen(
                cmd,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                startupinfo=self._hidden_startupinfo(),
                creationflags=creationflags,
            )
            self._running_subprocesses.append(process)
            if operation_name:
                self._operation_procs.setdefault(operation_name, []).append(process)
        except FileNotFoundError:
            self.log(f"❌ {cmd[0]} не найден.", tag="error")
            return False

        buffer = []
        last_flush = time.time()
        try:
            for line in process.stdout:
                line = line.strip()
                if not line:
                    continue

                if self._cancel_download and operation_name:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except Exception:
                        process.kill()
                    self.log("🛑 Процесс прерван из-за отмены операции.", tag="warn")
                    break

                if progress_parser:
                    parsed = progress_parser(line)
                    if parsed is False:
                        continue
                    if parsed is not None:
                        line = parsed

                buffer.append((line, "info"))
                if len(buffer) >= 50 or time.time() - last_flush > 0.2:
                    for text, tag in buffer:
                        self.log(text, tag)
                    buffer.clear()
                    last_flush = time.time()

            for text, tag in buffer:
                self.log(text, tag)
        except Exception as e:
            self.log(f"⚠ Ошибка при чтении вывода подпроцесса: {e}", tag="warn")

        try:
            process.wait(timeout=1800)
        except subprocess.TimeoutExpired:
            process.kill()
            self.log(f"⚠ {step_name} завис и был принудительно завершён.", tag="warn")
            self._remove_proc_from_lists(process, operation_name)
            return False

        self._remove_proc_from_lists(process, operation_name)

        if process.returncode != 0:
            self.log(f"❌ {step_name} ошибка {process.returncode}", tag="error")
            return False
        return True

    def _remove_proc_from_lists(self, process, operation_name):
        if process in self._running_subprocesses:
            self._running_subprocesses.remove(process)
        if operation_name and process in self._operation_procs.get(operation_name, []):
            self._operation_procs[operation_name].remove(process)

    # ================== Проверка подписи ==================

    def _verify_installer_signature(self, file_path):
        """Проверяет, что установщик имеет действительную цифровую подпись Authenticode."""
        if not self.settings.get("verify_installer_signature", True):
            return True
        try:
            ps_script = (
                f"$sig = Get-AuthenticodeSignature -FilePath '{file_path}'; "
                "if ($sig.Status -eq 'Valid') { 'Valid' } else { 'Invalid' }"
            )
            ps_path = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
            if not os.path.exists(ps_path):
                ps_path = "powershell.exe"
            result = subprocess.run(
                [ps_path, "-Command", ps_script],
                capture_output=True, text=True, timeout=15,
                startupinfo=self._hidden_startupinfo(),
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )
            return "Valid" in result.stdout
        except Exception as e:
            self.log(f"⚠ Не удалось проверить цифровую подпись: {e}", tag="warn")
            return False

    # ================== Системные операции ==================

    def _refresh_system_path(self):
        """Обновляет PATH текущего процесса из реестра Windows."""
        if not WINREG_AVAILABLE:
            return
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment") as key:
                system_path, _ = winreg.QueryValueEx(key, "PATH")
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
                user_path, _ = winreg.QueryValueEx(key, "PATH")
            system_path = os.path.expandvars(system_path)
            user_path = os.path.expandvars(user_path)
            os.environ["PATH"] = system_path + ";" + user_path
        except Exception as e:
            self.log(f"⚠ Не удалось обновить PATH из реестра: {e}", tag="warn")

    def _configure_git_for_stability(self):
        """Настраивает Git для устойчивой работы при медленном соединении."""
        try:
            subprocess.run(["git", "config", "--global", "http.postBuffer", "524288000"],
                           startupinfo=self._hidden_startupinfo(), check=False,
                           creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
            subprocess.run(["git", "config", "--global", "http.lowSpeedLimit", "0"],
                           startupinfo=self._hidden_startupinfo(), check=False,
                           creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
            subprocess.run(["git", "config", "--global", "http.lowSpeedTime", "999999"],
                           startupinfo=self._hidden_startupinfo(), check=False,
                           creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
            self.log("🔧 Git настроен для устойчивой работы (увеличен буфер, отключены таймауты).", tag="info")
        except Exception as e:
            self.log(f"⚠ Не удалось применить настройки Git: {e}", tag="warn")

    def _restart_computer(self):
        """Инициирует перезагрузку компьютера."""
        if sys.platform == "win32":
            try:
                subprocess.run(["shutdown", "/r", "/t", "10"], capture_output=True,
                               startupinfo=self._hidden_startupinfo(),
                               creationflags=subprocess.CREATE_NO_WINDOW)
                messagebox.showinfo(
                    "Перезагрузка",
                    "Компьютер перезагрузится через 10 секунд.\nСохраните свою работу."
                )
            except Exception as e:
                self.log(f"❌ Не удалось запустить перезагрузку: {e}", tag="error")

    # ================== Уведомления и подтверждения ==================

    def notify_tray(self, title, message):
        """Показывает уведомление в трее, если иконка доступна."""
        if self.tray_icon is not None and hasattr(self.tray_icon, 'notify'):
            try:
                self.tray_icon.notify(message, title)
            except Exception:
                pass

    def confirm_exit_if_running(self):
        """Возвращает True, если можно закрыть программу (нет активных процессов или пользователь подтвердил)."""
        active = []
        for inst in self._instances.values():
            srv = inst.get("srv")
            cli = inst.get("cli")
            if (srv and srv.poll() is None) or (cli and cli.poll() is None):
                active.append(inst["name"])
        if active:
            names = ", ".join(set(active))
            return messagebox.askyesno(
                "Завершение работы",
                f"Следующие сборки ещё запущены:\n{names}\n\n"
                "Все связанные процессы будут остановлены.\nПродолжить?",
                icon='warning'
            )
        return True

    # ================== Поиск инструментов ==================

    def _find_tool_in_path(self, name):
        return sys_find_tool(name)

    def _is_tool_installed(self, exe_name):
        exe_path = self._find_tool_in_path(exe_name)
        if not exe_path:
            return False
        try:
            subprocess.run(
                [exe_path, "--version"], capture_output=True, check=True,
                timeout=5, startupinfo=self._hidden_startupinfo(),
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )
            return True
        except Exception:
            return False

    def _is_python_installed(self):
        if getattr(sys, 'frozen', False):
            return self._is_tool_installed("python") or self._is_tool_installed("python3")
        return True

    def _get_python_installer_url(self):
        arch = platform.machine().lower()
        base_url = "https://www.python.org/ftp/python/3.14.7/"
        if arch in ("arm64", "aarch64"):
            return base_url + "python-3.14.7-arm64.exe"
        elif arch in ("x86_64", "amd64"):
            return base_url + "python-3.14.7-amd64.exe"
        else:
            return base_url + "python-3.14.7.exe"

    def _get_git_url(self):
        arch = platform.machine().lower()
        if arch in ("arm64", "aarch64"):
            return "https://github.com/git-for-windows/git/releases/download/v2.55.0.windows.3/Git-2.55.0.3-arm64.exe"
        else:
            return "https://github.com/git-for-windows/git/releases/download/v2.55.0.windows.3/Git-2.55.0.3-64-bit.exe"

    # ================== .NET SDK ==================

    def _get_installed_sdks(self):
        try:
            res = subprocess.run(
                ["dotnet", "--list-sdks"], capture_output=True, text=True,
                timeout=5, startupinfo=self._hidden_startupinfo(),
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )
            return re.findall(r'^(\d+\.\d+\.\d+)', res.stdout, re.MULTILINE)
        except Exception as e:
            self.log(f"⚠ Ошибка получения списка SDK: {e}", tag="warn")
            return []

    def _get_best_installed_sdk(self, required_version):
        installed = self._get_installed_sdks()
        if not installed:
            return None

        req_parts = required_version.split('.')
        if len(req_parts) < 2:
            return max(installed, key=lambda v: [int(x) for x in v.split('.')])

        req_major = int(req_parts[0])
        req_major_minor = '.'.join(req_parts[:2])

        matching = [v for v in installed if v.startswith(req_major_minor + '.')]
        if matching:
            matching.sort(key=lambda v: [int(x) for x in v.split('.')])
            return matching[-1]

        if self.settings.get("strict_sdk_major", True):
            return None

        compatible = [v for v in installed if int(v.split('.')[0]) >= req_major]
        if compatible:
            compatible.sort(key=lambda v: [int(x) for x in v.split('.')])
            return compatible[0]
        return None

    def _fix_dotnet_sdk(self, global_json_path):
        try:
            with open(global_json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            req = data.get("sdk", {}).get("version")
            if not req:
                return
        except Exception as e:
            self.log(f"⚠ Не удалось прочитать global.json: {e}", tag="warn")
            return

        best = self._get_best_installed_sdk(req)
        if best is None or best == req:
            if best is None and self.settings.get("strict_sdk_major", True):
                self.log(f"⚠ Требуемая SDK {req} не найдена и замена на другую major запрещена.", tag="warn")
            return

        self.log(f"⚠ Требуемая SDK {req} не найдена. Заменяем на ближайшую доступную: {best}", tag="warn")
        data["sdk"]["version"] = best
        try:
            with open(global_json_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            self.log(f"✅ global.json обновлён (SDK {best}).", tag="success")
        except Exception as e:
            self.log(f"❌ Ошибка обновления global.json: {e}", tag="error")

    def _get_dotnet_sdk_url(self, version):
        arch = platform.machine().lower()
        if arch in ("arm64", "aarch64"):
            win_arch = "arm64"
        elif arch in ("x86_64", "amd64"):
            win_arch = "x64"
        else:
            win_arch = "x86"
        return f"https://dotnetcli.azureedge.net/dotnet/Sdk/{version}/dotnet-sdk-{version}-win-{win_arch}.exe"

    def _print_build_diagnostics(self, build_path):
        try:
            ver = subprocess.run(
                ["dotnet", "--version"], capture_output=True, text=True,
                timeout=5, startupinfo=self._hidden_startupinfo(),
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            ).stdout.strip()
            self.log(f"Текущая версия .NET SDK: {ver}", tag="info")
        except Exception as e:
            self.log(f"⚠ Не удалось получить версию .NET SDK: {e}", tag="warn")
        gj = os.path.join(build_path, "global.json")
        if os.path.exists(gj):
            try:
                with open(gj, "r") as f:
                    data = json.load(f)
                    self.log(f"global.json: {json.dumps(data, indent=2)}", tag="info")
            except Exception as e:
                self.log(f"⚠ Не удалось прочитать global.json: {e}", tag="warn")
        self.log(f"Платформа: {sys.platform}, архитектура: {('x64' if sys.maxsize > 2 ** 32 else 'x86')}",
                 tag="info")

    # ================== Очистка кэшей ==================

    def cleanup_old_download_cache(self, days=30):
        cache_dir = self.download_manager.cache_dir
        if not cache_dir.exists():
            return
        now = time.time()
        for f in cache_dir.iterdir():
            if f.is_file() and (now - f.stat().st_mtime) > days * 86400:
                try:
                    f.unlink()
                    self.log(f"🧹 Удалён устаревший файл кэша: {f.name}", tag="info")
                except Exception:
                    pass

    def cleanup_unused_git_cache(self):
        """Удаляет git-кэши для сборок, отсутствующих в репозиториях."""
        git_cache_dir = Path(self.builds_dir) / ".git_cache"
        if not git_cache_dir.exists():
            return
        existing_repos = set(self.repositories.keys())
        for cache_name in [d.name for d in git_cache_dir.iterdir() if d.is_dir()]:
            if cache_name not in existing_repos:
                self._fast_remove_folder(str(git_cache_dir / cache_name), f"git-кэш {cache_name}")
                self.log(f"🧹 Удалён неиспользуемый git-кэш: {cache_name}", tag="info")

    # ================== Завершение процессов ==================

    def _kill_process_on_port(self, port):
        """Пытается освободить порт, но только если процесс относится к SS14/dotnet."""
        allowed_kw = ('content.server', 'content.client', 'dotnet', 'ss14', 'robust')

        if PSUTIL_AVAILABLE:
            for conn in psutil.net_connections(kind='udp'):
                if conn.laddr and conn.laddr.port == port:
                    try:
                        p = psutil.Process(conn.pid)
                        name = p.name().lower()
                        if any(kw in name for kw in allowed_kw):
                            self.log(f"🛑 Завершение процесса {p.name()} (PID {conn.pid}) с порта {port}", tag="warn")
                            p.kill()
                            return True
                        else:
                            self.log(f"⚠ Порт {port} занят процессом {p.name()} (PID {conn.pid}). "
                                     f"Не буду его завершать, так как он не относится к игре.", tag="warn")
                            return False
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass

        try:
            output = subprocess.run(["netstat", "-ano", "-p", "udp"], capture_output=True, text=True,
                                    startupinfo=self._hidden_startupinfo(),
                                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0).stdout
            for line in output.splitlines():
                if f":{port}" in line:
                    parts = line.split()
                    if not parts or not parts[-1].isdigit():
                        continue
                    pid = int(parts[-1])
                    tasklist = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"],
                                              capture_output=True, text=True,
                                              startupinfo=self._hidden_startupinfo(),
                                              creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0).stdout
                    process_name = ""
                    for tl_line in tasklist.splitlines()[1:]:
                        if str(pid) in tl_line:
                            process_name = tl_line.split()[0].lower()
                            break
                    if process_name and any(kw in process_name for kw in allowed_kw):
                        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True,
                                       startupinfo=self._hidden_startupinfo(),
                                       creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
                        self.log(f"🛑 Завершён процесс (PID {pid}) с портом {port}", tag="warn")
                        return True
                    else:
                        self.log(f"⚠ Порт {port} занят процессом PID {pid} (не игровой). Не буду убивать.",
                                 tag="warn")
                        return False
        except Exception as e:
            self.log(f"⚠ Не удалось освободить порт {port}: {e}", tag="warn")
        return False