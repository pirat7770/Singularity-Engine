# ui/main_window.py
import tkinter as tk
from tkinter import ttk, messagebox
import re
import os
import sys
import shutil
import subprocess
import threading
import time
import json
import urllib.request
import platform
import zipfile
from pathlib import Path
from collections import deque
import ctypes
import socket
import webbrowser
import pystray
from PIL import Image, ImageDraw
import threading
import psutil
try:
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

try:
    import pywinstyles
    PY_WINSTYLES = True
except ImportError:
    PY_WINSTYLES = False

from core.logger import logger
from core.port_allocator import PortAllocator
from core.config import ConfigManager
from core.download_manager import DownloadManager
from utils.system import hidden_startupinfo as sys_hidden_startupinfo, open_path as sys_open_path, find_tool_in_path as sys_find_tool
from ui.dialogs import DialogsMixin
from ui.constants import THEMES, BUSY_STATUSES, BUTTON_SEMANTICS, STATUS_ICONS

def resource_path(relative):
    if hasattr(sys, '_MEIPASS'):
        return Path(sys._MEIPASS) / relative
    return Path(__file__).parent.parent / relative


class SingularityEngineApp(tk.Tk, DialogsMixin):
    CONFIG_FILE = "config.json"
    CONFIG_VERSION = 56

    THEMES = THEMES
    BUSY_STATUSES = BUSY_STATUSES
    BUTTON_SEMANTICS = BUTTON_SEMANTICS
    STATUS_ICONS = STATUS_ICONS

    def __init__(self):
        super().__init__()
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("SingularityEngine.1")
        except Exception:
            pass
        self.VERSION = "1.86"
        self.tray_icon = None
        self._tray_thread = None
        self.title(f"Singularity Engine v{self.VERSION} - SS14 Manager")
        self.geometry("1200x800")
        self.configure(bg="#2b2b2b")
        icon_path = resource_path("Singularity-Engine.ico")
        png_icon = resource_path("Singularity-Engine2.png")
        if icon_path.exists():
            self.iconbitmap(str(icon_path))
        if png_icon.exists():
            self.iconphoto(True, tk.PhotoImage(file=str(png_icon)))

        if PY_WINSTYLES:
            try:
                pywinstyles.apply_style(self, "dark")
            except Exception as e:
                self.log(f"⚠ Не удалось применить тёмное оформление Windows: {e}", tag="warn")

        style = ttk.Style(self)
        style.theme_use("clam")

        style.configure("Treeview", borderwidth=0, relief="flat")
        style.configure(".", background="#2b2b2b", foreground="white", fieldbackground="#1e1e1e",
                        bordercolor="#008844", lightcolor="#2a4a3a", darkcolor="#1a3a2a")
        style.configure("Treeview", background="#1e1e1e", fieldbackground="#1e1e1e", foreground="white", rowheight=25)
        style.configure("Treeview.Heading", background="#2b2b2b", foreground="white", font=("Arial", 9, "bold"),
                        bordercolor="#008844", relief="flat")
        style.map("Treeview", background=[("selected", "#2d4a3a")])
        style.map("Treeview.Heading",
                  background=[("pressed", "#1a1a1a"), ("active", "#1e1e1e")],
                  foreground=[("pressed", "#00ff88"), ("active", "#00cc66")],
                  bordercolor=[("active", "#00cc66")])
        style.configure("TScrollbar", arrowcolor="#00cc66", arrowsize=12)
        style.map("TScrollbar",
                  arrowcolor=[("disabled", "#2a4a3a"), ("pressed", "#ffffff"), ("active", "#00ff88")])
        style.configure("Vertical.TScrollbar", background="#1a1a1a", troughcolor="#101010",
                        bordercolor="#008844", arrowcolor="#00cc66", darkcolor="#008844", lightcolor="#008844",
                        relief="flat")
        style.map("Vertical.TScrollbar",
                  background=[("pressed", "#006633"), ("active", "#008844")],
                  arrowcolor=[("pressed", "#00ff88"), ("active", "#00ff88")],
                  bordercolor=[("active", "#00cc66")])
        style.configure("Horizontal.TScrollbar", background="#1a1a1a", troughcolor="#101010",
                        bordercolor="#008844", arrowcolor="#00cc66", darkcolor="#008844", lightcolor="#008844")
        style.map("Horizontal.TScrollbar",
                  background=[("pressed", "#006633"), ("active", "#008844")],
                  arrowcolor=[("pressed", "#00ff88"), ("active", "#00ff88")],
                  bordercolor=[("active", "#00cc66")])
        style.configure("Hotbar.Horizontal.TProgressbar", troughcolor="#333333", bordercolor="#555555",
                        background="#00cc66", lightcolor="#00cc66", darkcolor="#00994d", thickness=18)
        style.configure("TPanedwindow", background="#2b2b2b")
        style.configure("TPanedwindow", sashrelief="flat", sashwidth=4, sashpad=0)

        self.config_manager = ConfigManager(self.CONFIG_FILE)
        self.download_manager = DownloadManager()

        self.builds_dir = Path.cwd() / "builds"
        self.builds_dir.mkdir(exist_ok=True)

        self.settings = self.config_manager.data.get("settings", self.config_manager.default_settings())
        self.repositories = self.config_manager.data.get("repositories", self.config_manager.default_repositories())
        self.log_filters = self.config_manager.data.get("log_filters", {"client": True, "server": True, "manager": True})

        self.after(100, self.check_required_tools)

        self._running_subprocesses = []
        self._instances = {}
        self._instance_counter = {}
        self._current_instance_id = None
        self._log_history = deque(maxlen=10000)
        self._active_operations = {}
        self._game_toggle_lock = False
        self._remove_repo_dialog = None
        self._nuget_disabled = False
        self._closing = False
        self._operation_procs = {}
        self._cancel_download = False
        self._last_download_log = -1
        self._operation_lock = False

        self.port_allocator = PortAllocator()

        self._refresh_system_path()

        self.settings_dialog = None
        self.settings_notebook = None
        self.settings_widgets = []
        self.settings_tabs = []

        self.withdraw()
        self.create_widgets()
        self.refresh_builds_list()
        self.after(2000, self._auto_refresh_instances)
        self.after(3000, self.check_for_updates)

        # Базовые теги менеджера (переработанные)
        self.console.tag_config("error", foreground="#ff5555", font=("Consolas", 10, "bold"))
        self.console.tag_config("success", foreground="#00ff88", font=("Consolas", 10, "bold"))
        self.console.tag_config("warn", foreground="#ffaa00")
        self.console.tag_config("info", foreground="#32CD32")
        self.console.tag_config("bold", foreground="#ffffff", font=("Consolas", 10, "bold"))
        self.console.tag_config("operation", foreground="#66ccff")
        self.console.tag_config("done", foreground="#00ffaa", font=("Consolas", 10, "bold"))
        self.console.tag_config("cancel", foreground="#cc66cc")

        self.deiconify()
        self.bind("<Button-1>", self._on_global_click)
        self.protocol("WM_DELETE_WINDOW", self._on_window_close)
        self.bind_all("<Control-c>", self.copy_selection)
        self.bind_all("<Control-C>", self.copy_selection)

    # ================== Вспомогательные системные методы ==================

    def _on_window_close(self):
        """Обрабатывает нажатие на крестик."""
        if self.settings.get("minimize_to_tray", True):
            self._hide_to_tray()
        else:
            self._on_closing()

    def check_for_updates(self):
        """Проверяет наличие новых релизов на GitHub и уведомляет пользователя."""
        from utils.updater import get_latest_release, GITHUB_REPO
        latest = get_latest_release()
        if latest:
            latest_version = latest.lstrip("v")
            if latest_version != self.VERSION:
                self.log(f"Доступна новая версия: {latest}", tag="done")
                if messagebox.askyesno("Обновление",
                                       f"Найдена новая версия {latest}.\nОткрыть страницу релиза?"):
                    import webbrowser
                    webbrowser.open(f"https://github.com/{GITHUB_REPO}/releases/latest")

    def _cleanup_broken_port_config(self, build_path):
        paths = [
            os.path.join(build_path, "bin", "Content.Server", "server_config.toml"),
            os.path.join(build_path, "bin", "Content.Server", "data", "server_config.toml"),
            os.path.join(build_path, "bin", "Content.Client", "data", "client_config.toml"),
        ]
        for p in paths:
            if not os.path.exists(p):
                continue
            try:
                with open(p, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                new_lines = [l for l in lines
                             if not re.match(r'^\s*net\.(port|connect_port)\s*=', l)]
                if len(new_lines) != len(lines):
                    with open(p, "w", encoding="utf-8") as f:
                        f.writelines(new_lines)
                    self.log(f"🧹 Из {os.path.basename(p)} удалены некорректные строки net.port", tag="info")
            except Exception as e:
                self.log(f"⚠ Не удалось почистить {p}: {e}", tag="warn")

    def stop_selected_build(self):
        name = self._get_selected_name()
        if name and self._is_game_running(name):
            self._stop_game(name)

    def _is_port_in_use(self, port):
        return self.port_allocator.is_port_in_use(port)

    def _allocate_port(self, start=1212, limit=200):
        return self.port_allocator.allocate()

    def _release_port(self, port):
        self.port_allocator.release(port)

    def _on_instance_select(self, event):
        selection = self.instance_tree.selection()
        if selection:
            instance_id = selection[0]
            self._current_instance_id = instance_id
            self._refresh_console_view()
        else:
            self._current_instance_id = None
            self._refresh_console_view()

    def _auto_refresh_instances(self):
        if not self._closing:
            self._refresh_instance_list()
            self.after(2000, self._auto_refresh_instances)

    def _on_instance_click(self, event):
        region = self.instance_tree.identify("region", event.x, event.y)
        column = self.instance_tree.identify_column(event.x)
        item = self.instance_tree.identify("item", event.x, event.y)
        if region == "cell" and column == "#4" and item:
            self._stop_instance(item)

    def _get_instance_resources(self, inst):
        cpu_percent = 0.0
        mem_bytes = 0
        if PSUTIL_AVAILABLE:
            processes = []
            for p in (inst["srv"], inst["cli"]):
                if p is not None and p.poll() is None:
                    try:
                        proc = psutil.Process(p.pid)
                        processes.append(proc)
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
            for proc in processes:
                try:
                    cpu_percent += proc.cpu_percent(interval=None)
                    mem_bytes += proc.memory_info().rss
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            mem_mb = mem_bytes / (1024 * 1024)
            cpu_str = f"{cpu_percent:.1f}%"
            mem_str = f"{mem_mb:.0f} MB"
        else:
            cpu_str = "N/A"
            mem_str = "N/A"
        return cpu_str, mem_str

    def _refresh_instance_list(self):
        self.instance_tree.delete(*self.instance_tree.get_children())
        for instance_id, inst in self._instances.items():
            srv_alive = inst["srv"] is not None and inst["srv"].poll() is None
            cli_alive = inst["cli"] is not None and inst["cli"].poll() is None

            if srv_alive and cli_alive:
                status = "Сервер+Клиент"
            elif srv_alive:
                status = "Сервер"
            elif cli_alive:
                status = "Клиент"
            else:
                status = "Завершён"

            cpu_str, mem_str = self._get_instance_resources(inst)
            self.instance_tree.insert("", "end", iid=instance_id,
                                      text=instance_id,
                                      values=(status, cpu_str, mem_str, "⏹"))

        if self._current_instance_id and self._current_instance_id in self._instances:
            self.instance_tree.selection_set(self._current_instance_id)

    def _refresh_system_path(self):
        try:
            import winreg
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

    def _hidden_startupinfo(self):
        return sys_hidden_startupinfo()

    def _on_closing(self):
        self._closing = True
        self.log("🛑 Завершение всех запущенных процессов...", tag="warn")
        for proc in self._running_subprocesses:
            try:
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        proc.kill()
            except Exception:
                pass
        for instance_id, inst in self._instances.items():
            for p in (inst["srv"], inst["cli"]):
                if p and p.poll() is None:
                    try:
                        p.terminate()
                        p.wait(timeout=2)
                    except:
                        try:
                            p.kill()
                        except:
                            pass
            for t in inst["threads"]:
                if t.is_alive():
                    t.join(timeout=1)

        if PSUTIL_AVAILABLE:
            for proc in psutil.process_iter(['pid', 'exe', 'cwd']):
                try:
                    exe = proc.info['exe']
                    cwd = proc.info['cwd']
                    if exe and os.path.normpath(exe).lower().startswith(str(self.builds_dir.resolve()).lower()):
                        proc.kill()
                    elif cwd and os.path.normpath(cwd).lower().startswith(str(self.builds_dir.resolve()).lower()):
                        proc.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

        for t in threading.enumerate():
            if t != threading.main_thread() and t.is_alive():
                t.join(timeout=1)

        self.port_allocator.reserved.clear()
        self.destroy()

    def _stop_selected_instance(self):
        selection = self.instance_tree.selection()
        if selection:
            self._stop_instance(selection[0])

    def _show_system_logs(self):
        self._current_instance_id = None
        self._refresh_console_view()
        self._refresh_instance_list()

    # ================== Поиск инструментов ==================
    def _find_tool_in_path(self, name):
        return sys_find_tool(name)

    def _is_tool_installed(self, exe_name):
        exe_path = self._find_tool_in_path(exe_name)
        if not exe_path:
            return False
        try:
            subprocess.run([exe_path, "--version"], capture_output=True, check=True,
                           timeout=5, startupinfo=self._hidden_startupinfo())
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

    # ================== Трей ==================

    def _create_tray_icon(self):
        """Создаёт иконку в системном трее."""
        try:
            icon_image = Image.open(resource_path("Singularity-Engine.ico"))
        except Exception as e:
            self.log(f"⚠ Не удалось загрузить иконку для трея: {e}", tag="warn")
            return

        try:
            menu = pystray.Menu(
                pystray.MenuItem("Открыть", self._restore_from_tray),
                pystray.MenuItem("Выход", self._exit_from_tray),
            )
            self.tray_icon = pystray.Icon(
                "SingularityEngine",
                icon_image,
                "Singularity Engine",
                menu
            )
            self._tray_thread = threading.Thread(target=self.tray_icon.run, daemon=True)
            self._tray_thread.start()
        except Exception as e:
            self.log(f"⚠ Не удалось создать иконку в трее: {e}", tag="warn")
            self.tray_icon = None

    def _restore_from_tray(self):
        """Восстанавливает окно из трея."""
        self.after(0, self._show_window)

    def _show_window(self):
        self.deiconify()
        self.state('normal')
        self.lift()
        self.focus_force()

    def _hide_to_tray(self):
        """Сворачивает окно в трей."""
        self.withdraw()
        if self.tray_icon is None:
            self._create_tray_icon()

    def _exit_from_tray(self):
        """Полностью завершает программу из трея."""
        if self.tray_icon:
            self.tray_icon.stop()
        self.after(0, self._on_closing)

    # ================== Установка зависимостей ==================
    def _offer_sdk_install_before_build(self, required_version, build_name, build_path):
        if self.settings.get("auto_install_deps", False):
            self.log(f"Автоматическая установка .NET SDK {required_version}...", tag="bold")
            self._download_and_install_sdk(required_version, build_name, build_path)
            return True
        else:
            msg = (f"Для сборки '{build_name}' требуется .NET SDK {required_version}, "
                   "которая не установлена.\n\n"
                   "Программа может автоматически скачать и установить её сейчас.\n\n"
                   "Продолжить?")
            if messagebox.askyesno("Требуется .NET SDK", msg):
                self._download_and_install_sdk(required_version, build_name, build_path)
                return True
            else:
                self.log("⚠ Сборка отменена из-за отсутствия требуемой версии SDK.", tag="warn")
                return False

    def _offer_python_install(self):
        url = self._get_python_installer_url()
        msg = ("Для работы требуется Python.\n\n"
               "Хотите автоматически скачать и установить его?\n\n"
               "⚠️ ВАЖНО: При установке обязательно отметьте опцию "
               '"Add python.exe to PATH"!')
        if messagebox.askyesno("Установка Python", msg):
            self._download_and_run_installer("Python", url)

    def check_required_tools(self):
        missing = []
        if not self._is_tool_installed("git"):
            missing.append("Git")
        if not self._is_python_installed():
            self.log("⚠ Python не найден. Для установки откройте настройки (⚙) или меню «Репозитории».", tag="warn")
            self.log("💡 При установке Python обязательно отметьте 'Add python.exe to PATH'.", tag="bold")
            return
        if not self._is_tool_installed("dotnet"):
            missing.append(".NET SDK")
        else:
            installed = self._get_installed_sdks()
            has_compatible = any(v.startswith("9.") or v.startswith("10.") for v in installed)
            if not has_compatible:
                missing.append(".NET SDK 9/10")

        if missing:
            msg = "Не найдены: " + ", ".join(missing)
            self.log(msg, tag="warn")
            self.log("Вы можете установить их через меню 'Репозитории' → 'Установить недостающие инструменты'.", tag="info")
        else:
            self.log("✅ Все необходимые инструменты найдены.", tag="success")

    def install_missing_tools(self):
        missing = []
        if not self._is_tool_installed("git"):
            missing.append(("Git", self._get_git_url()))
        if not self._is_python_installed():
            self._offer_python_install()
            return
        if not self._is_tool_installed("dotnet"):
            missing.append((".NET SDK", "10.0.302"))
        else:
            installed = self._get_installed_sdks()
            has_compatible = any(v.startswith("9.") or v.startswith("10.") for v in installed)
            if not has_compatible:
                missing.append((".NET SDK 9/10", "10.0.302"))
        if not missing:
            messagebox.showinfo("Информация", "Все необходимые инструменты уже установлены.")
            return
        msg = "Будут установлены:\n\n" + "\n".join(f"• {n}" for n, _ in missing)
        msg += "\n\nПродолжить?"
        if messagebox.askyesno("Установка зависимостей", msg):
            for name, url in missing:
                if "SDK" in name:
                    self._download_and_install_sdk(url, None, None)
                else:
                    self._download_and_run_installer(name, url)

    def _download_and_run_installer(self, name, url):
        self.log(f"⬇ Подготовка загрузки {name}...", tag="bold")
        self.progress_bar.config(mode="determinate")
        self.progress_var.set(0)
        self.lbl_speed.config(text=f"Загрузка {name}...")
        dest_name = url.split("/")[-1]

        def download_thread():
            try:
                self._last_download_log = -1
                self._download_start = time.time()
                installer_path = self.download_manager.download(
                    url, dest_name, progress_callback=self._download_progress
                )
                if not installer_path:
                    raise Exception("Не удалось скачать установщик")

                ps_path = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
                if not os.path.exists(ps_path):
                    ps_path = "powershell.exe"
                ps_args = [ps_path, "-Command",
                           f'Start-Process -FilePath "{installer_path}" -Verb RunAs -Wait']
                self.log(f"🔧 Запуск установщика {name}...", tag="bold")
                result = subprocess.run(ps_args, startupinfo=self._hidden_startupinfo(),
                                        capture_output=True, text=True)
                if result.returncode != 0:
                    self.log(f"❌ Установка {name} не была завершена (код {result.returncode}). "
                             f"Возможно, отменён запрос UAC.", tag="error")
                    return

                self.log(f"⏳ Установка {name} завершена.", tag="bold")
                if name == "Python":
                    if not self._is_python_installed():
                        self.log("⚠ Python не найден в PATH после установки.", tag="warn")
                        messagebox.showwarning(
                            "Требуется переустановка Python",
                            "Python был установлен, но не добавлен в системный PATH.\n\n"
                            "Для корректной работы менеджера:\n"
                            "1. Запустите установщик Python ещё раз.\n"
                            "2. Обязательно отметьте галочку 'Add python.exe to PATH'.\n"
                            "3. После установки перезапустите это приложение.\n\n"
                            "Либо добавьте путь к python.exe вручную в переменные среды."
                        )
                    else:
                        self.log("✅ Python успешно установлен и доступен в PATH.", tag="success")

                self.log("💡 Для обновления системного PATH может потребоваться перезапуск менеджера.", tag="info")
                if messagebox.askyesno("Перезагрузка компьютера",
                                       f"Установка {name} завершена.\n\n"
                                       "Для корректной работы рекомендуется перезагрузить компьютер.\n\n"
                                       "Хотите перезагрузить сейчас?"):
                    self._restart_computer()
            except Exception as e:
                self.log(f"❌ Ошибка при работе с {name}: {e}", tag="error")
            finally:
                self.after(0, self.progress_bar.stop)
                self.after(0, lambda: self.progress_bar.config(mode="determinate"))
                self.after(0, lambda: self.progress_var.set(0))
                self.after(0, lambda: self.lbl_speed.config(text="0.00 MiB/s"))

        threading.Thread(target=download_thread, daemon=True).start()

    def _restart_computer(self):
        if sys.platform == "win32":
            try:
                subprocess.run(["shutdown", "/r", "/t", "10"], capture_output=True)
                messagebox.showinfo("Перезагрузка", "Компьютер перезагрузится через 10 секунд.\nСохраните свою работу.")
            except Exception as e:
                self.log(f"❌ Не удалось запустить перезагрузку: {e}", tag="error")

    # ================== Конфигурация ==================
    def load_config(self):
        return self.repositories, self.log_filters

    def default_settings(self):
        return self.config_manager.default_settings()

    def load_settings(self):
        return self.settings

    def _on_console_key(self, event):
        if (event.state & 0x4) and event.keysym.lower() in ("c", "insert"):
            return None
        return "break"

    def save_settings(self):
        self.config_manager.data["repositories"] = self.repositories
        self.config_manager.data["log_filters"] = self.log_filters
        self.config_manager.data["settings"] = self.settings
        self.config_manager.save()

    def save_config(self):
        self.save_settings()

    # ================== GUI ==================
    def create_widgets(self):
        self._create_menu_bar()
        self.paned_window = ttk.PanedWindow(self, orient="horizontal")
        self.paned_window.pack(fill="both", expand=True, padx=5, pady=5)
        self._create_left_panel()
        self._create_right_panel()
        self._create_status_bar()
        self.apply_theme(self.settings.get("theme", "Стандартная"))
        self.after(2000, self._auto_refresh_instances)

    def _create_menu_bar(self):
        self.menu_bar = tk.Frame(self, bg="#2b2b2b", highlightbackground="#008844", highlightthickness=1, height=28)
        self.menu_bar.pack(side="top", fill="x")

        self.settings_btn = tk.Button(self.menu_bar, text="⚙",
                                      bg="#2b2b2b", fg="#00cc66",
                                      activebackground="#4a4d50", activeforeground="#00ff88",
                                      relief="flat", bd=0, font=("Arial", 11),
                                      highlightbackground="#008844", highlightthickness=1,
                                      command=self.open_settings_dialog)
        self.settings_btn.pack(side="left", padx=(5, 2))

        self.menu_sep1 = tk.Frame(self.menu_bar, bg="#008844", width=1)
        self.menu_sep1.pack(side="left", fill="y", padx=2)

        self.repo_btn = tk.Button(self.menu_bar, text="Репозитории",
                                  bg="#2b2b2b", fg="#00cc66",
                                  activebackground="#4a4d50", activeforeground="#00ff88",
                                  relief="flat", bd=0, font=("Arial", 9),
                                  command=self._toggle_repo_menu)
        self.repo_btn.pack(side="left", padx=2)

        self.menu_sep2 = tk.Frame(self.menu_bar, bg="#008844", width=1)
        self.menu_sep2.pack(side="left", fill="y", padx=2)

        self._repo_menu_window = None
        self._trash_menu_window = None

    def _toggle_repo_menu(self):
        if self._repo_menu_window and self._repo_menu_window.winfo_exists():
            self._close_repo_menu()
        else:
            self._open_repo_menu()

    def _open_repo_menu(self):
        self._close_repo_menu()
        t = self.THEMES.get(self.settings.get("theme", "Стандартная"))

        menu = tk.Toplevel(self)
        menu.overrideredirect(True)
        menu.configure(bg=t["menu_bg"], bd=0, highlightthickness=0)

        commands = [
            ("Добавить", self.add_repository_dialog),
            ("Удалить", self.remove_repository_dialog),
            ("Очистить кэш", self.clear_cache),
            ("Установить недостающие инструменты", self.install_missing_tools),
        ]
        for text, cmd in commands:
            btn = tk.Button(menu, text=text, bg=t["menu_bg"], fg=t["menu_fg"],
                            activebackground=t["menu_active_bg"], activeforeground=t["menu_active_fg"],
                            relief="flat", bd=0, font=("Arial", 9),
                            command=lambda c=cmd: (c(), self._close_repo_menu()))
            btn.pack(fill="x", padx=1, pady=1)

        x = self.repo_btn.winfo_rootx()
        y = self.repo_btn.winfo_rooty() + self.repo_btn.winfo_height()
        x = x + self.repo_btn.winfo_width() - menu.winfo_reqwidth()
        menu.geometry(f"+{x}+{y}")
        menu.bind("<FocusOut>", lambda e: self._close_repo_menu())
        menu.focus_set()
        self._repo_menu_window = menu

    def _close_repo_menu(self):
        if self._repo_menu_window and self._repo_menu_window.winfo_exists():
            self._repo_menu_window.destroy()
        self._repo_menu_window = None

    def _on_instance_right_click(self, event):
        item = self.instance_tree.identify("item", event.x, event.y)
        if not item:
            return
        self.instance_tree.selection_set(item)
        instance_id = item
        menu = tk.Menu(self, tearoff=0,
                       bg=self._get_theme_color("menu_bg"),
                       fg=self._get_theme_color("menu_fg"),
                       activebackground=self._get_theme_color("menu_active_bg"),
                       activeforeground=self._get_theme_color("menu_active_fg"))
        menu.add_command(label="Остановить экземпляр", command=lambda: self._stop_instance(instance_id))
        menu.add_command(label="Показать логи", command=lambda: self._on_instance_select(None, instance_id))
        menu.post(event.x_root, event.y_root)

    def _create_left_panel(self):
        left_frame = tk.Frame(self.paned_window, bg="#722f37", width=350)
        self.left_frame = left_frame
        self.paned_window.add(left_frame, weight=1)

        self.lbl_available = tk.Label(left_frame, text="Доступные сборки", bg="#722f37", fg="white",
                                      font=("Arial", 10, "bold"))
        self.lbl_available.pack(anchor="w", pady=(0, 5))

        tree_frame = tk.Frame(left_frame, bg="#2b2b2b", highlightthickness=2,
                              highlightbackground="#008844", highlightcolor="#008844",
                              takefocus=0)
        self.tree_frame = tree_frame
        tree_frame.pack(fill="both", expand=True)

        self.tree = ttk.Treeview(tree_frame, columns=("status", "mode"), selectmode="browse", height=8)
        self.tree.configure(takefocus=False)
        self.tree.heading("#0", text="Имя сборки", anchor="w")
        self.tree.heading("status", text="Статус", anchor="center")
        self.tree.heading("mode", text="Режим", anchor="center")
        self.tree.column("#0", width=140)
        self.tree.column("status", width=150, anchor="center")
        self.tree.column("mode", width=70, anchor="center")

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview,
                            style="Dark.Vertical.TScrollbar")
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True, padx=1, pady=1)

        self.tree.bind("<<TreeviewSelect>>", self.on_build_select)
        self.tree.bind("<Button-1>", self._on_tree_click)
        self.tree.bind("<Button-3>", self._on_tree_right_click)
        self.tree.bind("<FocusIn>", lambda e: self.focus_set())

        self.lbl_instances = tk.Label(left_frame, text="Активные экземпляры", bg="#2b2b2b", fg="white",
                                      font=("Arial", 10, "bold"))
        self.lbl_instances.pack(anchor="w", pady=(10, 5))

        instance_frame = tk.Frame(left_frame, bg="#2b2b2b", highlightthickness=1,
                                  highlightbackground="#008844", highlightcolor="#008844")
        self.instance_frame = instance_frame
        instance_frame.pack(fill="x", pady=(0, 5))

        instance_vsb = ttk.Scrollbar(instance_frame, orient="vertical",
                                     style="Dark.Vertical.TScrollbar")

        self.instance_tree = ttk.Treeview(instance_frame, columns=("status", "cpu", "mem", "stop"),
                                          selectmode="browse", height=4,
                                          yscrollcommand=instance_vsb.set)
        instance_vsb.config(command=self.instance_tree.yview)

        self.instance_tree.configure(takefocus=False)
        self.instance_tree.heading("#0", text="Экземпляр", anchor="w")
        self.instance_tree.heading("status", text="Статус", anchor="center")
        self.instance_tree.heading("cpu", text="CPU", anchor="center")
        self.instance_tree.heading("mem", text="RAM", anchor="center")
        self.instance_tree.heading("stop", text="", anchor="center")
        self.instance_tree.column("#0", width=100)
        self.instance_tree.column("status", width=100, anchor="center")
        self.instance_tree.column("cpu", width=50, anchor="center")
        self.instance_tree.column("mem", width=70, anchor="center")
        self.instance_tree.column("stop", width=30, anchor="e")

        instance_vsb.pack(side="right", fill="y")
        self.instance_tree.pack(fill="both", expand=True, padx=1, pady=1)

        self.instance_tree.bind("<<TreeviewSelect>>", self._on_instance_select)
        self.instance_tree.bind("<Button-1>", self._on_instance_click)
        self.instance_tree.bind("<Button-3>", self._on_instance_right_click)

        self.btn_show_system_logs = tk.Button(left_frame, text="Системные логи",
                                              bg="#4a4d50", fg="white",
                                              activebackground="#4a4d50", activeforeground="#00ff88",
                                              relief="flat", bd=1,
                                              highlightbackground="#008844", highlightthickness=0,
                                              command=self._show_system_logs)
        self.btn_show_system_logs.pack(fill="x", pady=2)

        self.lbl_actions = tk.Label(left_frame, text="Действия", bg="#2b2b2b", fg="white",
                                    font=("Arial", 10, "bold"))
        self.lbl_actions.pack(anchor="w", pady=(10, 5))

        self.btn_install = tk.Button(left_frame, text="Установить", bg="#4a4d50", fg="white",
                                     command=self.start_installation, state="disabled")
        self.btn_install.pack(fill="x", pady=2)

        self.btn_run = tk.Button(left_frame, text="Запустить (Serv+Client)", bg="#4a4d50", fg="white",
                                 state="disabled", command=self.toggle_game)
        self.btn_run.pack(fill="x", pady=2)

        self.btn_open_folder = tk.Button(left_frame, text="Открыть папку", bg="#4a4d50", fg="white",
                                         state="disabled", command=self.open_build_folder)
        self.btn_open_folder.pack(fill="x", pady=2)

        self.btn_open_upload = tk.Button(left_frame, text="Открыть UploadFolder", bg="#4a4d50", fg="white",
                                         state="disabled", command=self.open_upload_folder)
        self.btn_open_upload.pack(fill="x", pady=2)

        self.btn_reinstall = tk.Button(left_frame, text="Переустановить", bg="#4a4d50", fg="white",
                                       state="disabled", command=self.reinstall_build)
        self.btn_reinstall.pack(fill="x", pady=2)

        self.btn_delete = tk.Button(left_frame, text="Удалить файлы", bg="#8a3a3a", fg="white",
                                    state="disabled", command=self.delete_build)
        self.btn_delete.pack(fill="x", pady=2)

        self.btn_clean_rebuild = tk.Button(left_frame, text="Очистить кэш и пересобрать", bg="#4a6d4a",
                                           fg="white", state="disabled", command=self.clean_rebuild)
        self.btn_clean_rebuild.pack(fill="x", pady=2)

    def toggle_favorite(self, name):
        repo_data = self.repositories[name]
        repo_data["favorite"] = not repo_data.get("favorite", False)
        self.save_config()
        self.refresh_builds_list()
        self.tree.selection_set(name)
        self.tree.see(name)
        self.log(f"⭐ Избранное обновлено для '{name}'.", tag="info")

    def _on_tree_right_click(self, event):
        item = self.tree.identify("item", event.x, event.y)
        if not item:
            return
        self.tree.selection_set(item)
        name = item
        status = self.get_build_status(name)
        running = self._is_game_running(name)

        t = self.THEMES.get(self.settings.get("theme", "Стандартная"))
        menu = tk.Menu(self, tearoff=0, bg=t["menu_bg"], fg=t["menu_fg"],
                       activebackground=t["menu_active_bg"], activeforeground=t["menu_active_fg"],
                       bd=0, relief="flat")

        if status not in self.BUSY_STATUSES:
            is_fav = self.repositories[name].get("favorite", False)
            fav_label = "Убрать из избранного" if is_fav else "В избранное"
            menu.add_command(label=fav_label, command=lambda: self.toggle_favorite(name))
            menu.add_separator()
            menu.add_command(label="Переименовать", command=lambda: self.rename_repository(name))
            menu.add_command(label="Изменить URL", command=lambda: self.edit_repository_url(name))
            menu.add_separator()

        if running:
            menu.add_command(label="Запустить ещё", command=lambda: self._start_game(name))
            menu.add_command(label="Остановить все экземпляры", command=lambda: self._stop_game(name))
        elif status not in self.BUSY_STATUSES:
            if status == "missing":
                menu.add_command(label="Установить", command=lambda: self.start_installation())
            elif status == "installed":
                menu.add_command(label="Запустить", command=lambda: self._start_game(name))
                menu.add_command(label="Переустановить", command=lambda: self.reinstall_build())
                menu.add_command(label="Удалить", command=lambda: self.delete_build())
                if os.path.exists(os.path.join(self.builds_dir, name, ".git")):
                    menu.add_command(label="Обновить", command=lambda: self.update_build(name))
                    menu.add_command(label="Проверить обновления", command=lambda: self.check_repository_updates(name))
            else:
                menu.add_command(label="Переустановить", command=lambda: self.reinstall_build())
                menu.add_command(label="Удалить", command=lambda: self.delete_build())
            menu.add_command(label="Открыть папку", command=lambda: self.open_build_folder())

        menu.post(event.x_root, event.y_root)

    def copy_selection(self, event=None):
        try:
            selected_text = self.console.get("sel.first", "sel.last")
            self.clipboard_clear()
            self.clipboard_append(selected_text)
            return "break"
        except tk.TclError:
            if self.focus_get() == self.console:
                full_text = self.console.get("1.0", "end").strip()
                if full_text:
                    self.clipboard_clear()
                    self.clipboard_append(full_text)
                    return "break"
        return None

    def _create_right_panel(self):
        right_frame = tk.Frame(self.paned_window, bg="#2b2b2b")
        self.right_frame = right_frame
        self.paned_window.add(right_frame, weight=3)

        filter_frame = tk.Frame(right_frame, bg="#2b2b2b")
        self.filter_frame = filter_frame
        filter_frame.pack(fill="x", pady=(0, 2))
        self.lbl_console_header = tk.Label(filter_frame, text="Консоль выполнения:", bg="#2b2b2b",
                                           fg="white", font=("Arial", 10, "bold"))
        self.lbl_console_header.pack(side="left")
        self.filter_vars = {
            "client": tk.BooleanVar(value=self.log_filters.get("client", True)),
            "server": tk.BooleanVar(value=self.log_filters.get("server", True)),
            "manager": tk.BooleanVar(value=self.log_filters.get("manager", True))
        }
        self.filter_checkbuttons = []
        for key, text in [("client", "Клиент"), ("server", "Сервер"), ("manager", "Менеджер")]:
            cb = tk.Checkbutton(filter_frame, text=text, variable=self.filter_vars[key],
                                bg="#2b2b2b", fg="white", selectcolor="#2b2b2b",
                                activebackground="#2b2b2b", activeforeground="white",
                                command=lambda k=key: self._on_filter_changed(k))
            cb.pack(side="left", padx=5)
            self.filter_checkbuttons.append(cb)

        console_frame = tk.Frame(right_frame, bg="#000000",
                                 highlightthickness=2,
                                 highlightbackground="#008844",
                                 highlightcolor="#008844")
        self.console_frame = console_frame
        console_frame.pack(fill="both", expand=True, padx=1, pady=1)

        self.console = tk.Text(console_frame, bg="#000000", fg="#33ff33", font=("Consolas", 10),
                               state="normal",
                               wrap="word",
                               highlightthickness=0, borderwidth=0,
                               insertbackground="#000000",
                               selectbackground="#2d4a3a",
                               selectforeground="white",
                               inactiveselectbackground="#2d4a3a",
                               exportselection=False)
        self.console.bind("<Key>", self._on_console_key)
        self.console.configure(highlightcolor="#000000", highlightbackground="#000000")

        vsb_console = ttk.Scrollbar(console_frame, orient="vertical", command=self.console.yview,
                                    style="Dark.Vertical.TScrollbar")
        self.console.configure(yscrollcommand=vsb_console.set)
        vsb_console.pack(side="right", fill="y")
        self.console.pack(fill="both", expand=True)

    def _create_status_bar(self):
        hotbar_frame = tk.Frame(self, bg="#1a1a1a", highlightbackground="#008844", highlightthickness=1)
        self.hotbar_frame = hotbar_frame
        hotbar_frame.pack(side="bottom", fill="x", padx=5, pady=(0, 5))

        self.btn_copy_logs = tk.Button(hotbar_frame, text="Скопировать логи", bg="#2b2b2b", fg="#00cc66",
                                       activebackground="#3c3f41", activeforeground="#00ff88",
                                       relief="flat", bd=1, highlightbackground="#00cc66",
                                       command=self.copy_logs, font=("Arial", 9))
        self.btn_copy_logs.pack(side="left", padx=(5, 2), pady=5)
        self.btn_clear_console = tk.Button(hotbar_frame, text="Очистить консоль", bg="#2b2b2b", fg="#00cc66",
                                           activebackground="#3c3f41", activeforeground="#00ff88",
                                           relief="flat", bd=1, highlightbackground="#00cc66",
                                           command=self.clear_console, font=("Arial", 9))
        self.btn_clear_console.pack(side="left", padx=2, pady=5)

        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(hotbar_frame, orient="horizontal", length=300,
                                            mode="determinate", variable=self.progress_var,
                                            style="Hotbar.Horizontal.TProgressbar")
        self.progress_bar.pack(side="right", padx=(5, 10), pady=8)

        self.lbl_speed = tk.Label(hotbar_frame, text="0.00 MiB/s", bg="#1a1a1a", fg="#00ff88",
                                  font=("Consolas", 10, "bold"))
        self.lbl_speed.pack(side="right", padx=5, pady=5)

    def _on_global_click(self, event):
        widget = event.widget
        while widget is not None:
            if widget == self.console:
                return
            widget = widget.master

    def _get_selected_name(self):
        selected = self.tree.selection()
        if selected:
            return selected[0]
        return None

    def _on_filter_changed(self, key):
        self.log_filters[key] = self.filter_vars[key].get()
        self.save_config()
        self._refresh_console_view()

    def _on_tree_click(self, event):
        region = self.tree.identify("region", event.x, event.y)
        column = self.tree.identify_column(event.x)
        item = self.tree.identify("item", event.x, event.y)
        if region != "cell" or column != "#2" or not item:
            return
        name = item
        status = self.get_build_status(name)
        if status in self.BUSY_STATUSES or self._is_game_running(name):
            return
        current_mode = self.repositories[name].get("mode", "Debug")
        new_mode = "Release" if current_mode == "Debug" else "Debug"
        self.repositories[name]["mode"] = new_mode
        self.save_config()
        self.refresh_builds_list()
        self.tree.selection_set(name)
        self.log(f"Режим сборки для '{name}' изменён на {new_mode}. Для применения переустановите сборку.", tag="info")

    def _set_operation(self, name, status):
        self._active_operations[name] = status
        self.after(0, self.refresh_builds_list)

    def _end_operation(self, name):
        if name not in self._active_operations:
            return  # операция уже завершена
        self._active_operations.pop(name, None)
        self._operation_lock = False
        self.progress_bar.stop()
        self.progress_bar.config(mode="determinate")
        self.progress_var.set(0)
        self.lbl_speed.config(text="0.00 MiB/s")
        self.after(0, self.refresh_builds_list)
        self.after(0, self._reenable_buttons)
        self.log(f"✔ Операция для '{name}' завершена", tag="done")

    def _check_disk_space(self):
        free = shutil.disk_usage(self.builds_dir).free
        if free < 1_000_000_000:
            self.log("⚠ На диске мало места. Сборка может завершиться ошибкой.", tag="warn")

    def stop_operation(self, name):
        self._cancel_download = True
        if name not in self._active_operations:
            return
        self.log(f"🛑 Отмена операции для '{name}'...", tag="cancel")

        # Завершаем все процессы операции, включая дочерние
        for proc in self._operation_procs.get(name, []):
            if proc.poll() is None:
                try:
                    # Убиваем дерево процессов через taskkill
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                                   capture_output=True, text=True, timeout=10)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass

        # Дополнительно убиваем все процессы, связанные с папкой сборки
        build_path = os.path.join(self.builds_dir, name)
        self.kill_processes_locking_folder(build_path)

        # Пауза для освобождения файлов
        time.sleep(1)

        # Удаляем папку
        if not self._fast_remove_folder(build_path, name):
            # Если не удалось, пробуем еще раз после задержки
            time.sleep(2)
            self._fast_remove_folder(build_path, name)

        self._end_operation(name)
        self.log(f"✅ Операция для '{name}' отменена, файлы удалены.", tag="success")

    def log(self, text, tag="info"):
        self._log_history.append((text, tag))
        if self._current_instance_id is None:
            self.after(0, self._refresh_console_view)

        if tag == "error":
            logger.error(text)
        elif tag == "warn":
            logger.warning(text)
        else:
            logger.info(text)

    def _flush_log(self):
        self._log_timer = None
        self.console.config(state="normal")
        count = 0
        while self._log_pending and count < 100:
            text, tag = self._log_pending.popleft()
            self.console.insert("end", text + "\n", tag)
            count += 1
        self.console.see("end")
        self.console.config(state="disabled")
        if self._log_pending:
            self._log_timer = self.after(100, self._flush_log)

    def _rebuild_console(self):
        self.console.config(state="normal")
        self.console.delete("1.0", "end")
        for text, tag in self._log_history:
            category = self._get_tag_category(tag)
            if self.log_filters.get(category, True):
                self.console.insert("end", text + "\n", tag)
        self.console.see("end")
        self.console.config(state="disabled")

    def _get_tag_category(self, tag):
        if tag.startswith("server"):
            return "server"
        elif tag.startswith("client"):
            return "client"
        else:
            return "manager"

    def _find_executables(self, build_path):
        for base in ["space-station-14", ""]:
            if base:
                server = os.path.join(build_path, base, "bin", "Content.Server", "Content.Server.exe")
                client = os.path.join(build_path, base, "bin", "Content.Client", "Content.Client.exe")
            else:
                server = os.path.join(build_path, "bin", "Content.Server", "Content.Server.exe")
                client = os.path.join(build_path, "bin", "Content.Client", "Content.Client.exe")
            yield server, client

    def get_build_status(self, name):
        if name in self._active_operations:
            return self._active_operations[name]
        build_path = os.path.join(self.builds_dir, name)
        if not os.path.exists(build_path):
            return "missing"
        has_git = os.path.exists(os.path.join(build_path, ".git"))
        has_both = False
        for server_exe, client_exe in self._find_executables(build_path):
            if os.path.exists(server_exe) and os.path.exists(client_exe):
                has_both = True
                break
        if has_git and has_both:
            return "installed"
        if has_git and not has_both:
            has_any = False
            for server_exe, client_exe in self._find_executables(build_path):
                if os.path.exists(server_exe) or os.path.exists(client_exe):
                    has_any = True
                    break
            if has_any:
                return "partial_build"
            else:
                return "clone_incomplete"
        if not has_git:
            return "clone_incomplete"
        return "unknown"

    def _is_game_running(self, name):
        for inst in self._instances.values():
            if inst["name"] == name:
                if (inst["srv"] and inst["srv"].poll() is None) or (inst["cli"] and inst["cli"].poll() is None):
                    return True
        return False

    def refresh_builds_list(self):
        selected = self.tree.selection()
        selected_name = selected[0] if selected else None
        self.tree.delete(*self.tree.get_children())

        def sort_priority(name):
            status = self.get_build_status(name)
            if status in self.BUSY_STATUSES:
                return 0
            if status == "installed":
                return 1
            return 2

        sorted_repos = sorted(
            self.repositories.items(),
            key=lambda item: (
                sort_priority(item[0]),
                not item[1].get("favorite", False),
                item[0].lower()
            )
        )

        for name, repo_data in sorted_repos:
            raw_status = self.get_build_status(name)
            running = self._is_game_running(name)
            if raw_status in self.BUSY_STATUSES:
                status_text = self.STATUS_ICONS.get(raw_status, raw_status)
            elif running:
                status_text = "▶ Запущено"
            elif raw_status in self.STATUS_ICONS:
                status_text = self.STATUS_ICONS[raw_status]
            else:
                status_text = raw_status

            mode = repo_data.get("mode", "Debug")
            mode_display = "⚙ Debug" if mode == "Debug" else "🚀 Release"
            prefix = "★ " if repo_data.get("favorite", False) else "☆ "
            self.tree.insert("", "end", iid=name, text=prefix + name,
                             values=(status_text, mode_display))

        if selected_name and selected_name in self.repositories:
            self.tree.selection_set(selected_name)
            self.tree.see(selected_name)
        self.on_build_select(None)

    def open_upload_folder(self):
        upload_path = Path(os.environ.get("APPDATA", "")) / "Space Station 14" / "data" / "UploadFolder"
        if upload_path.exists():
            sys_open_path(upload_path)
        else:
            messagebox.showinfo("Папка не найдена", f"UploadFolder не существует:\n{upload_path}")

    def download_prebuilt(self, name, url):
        if name in self._active_operations:
            return
        self._start_operation(name, "Загрузка готовой сборки...", progress_mode="determinate")
        self.log(f"📦 Загрузка готовой сборки для '{name}'...", tag="bold")
        self._cancel_download = False

        def _download():
            zip_path = None
            try:
                self._last_download_log = -1
                self._download_start = time.time()
                zip_path = os.path.join(self.builds_dir, f"{name}.zip")
                self._download_start = time.time()
                urllib.request.urlretrieve(url, zip_path, self._download_progress)
                self.log("✅ Загрузка завершена. Распаковка...", tag="success")
                with zipfile.ZipFile(zip_path, 'r') as zf:
                    zf.extractall(os.path.join(self.builds_dir, name))
                os.remove(zip_path)
                self.log("✅ Готовая сборка установлена.", tag="success")
            except Exception as e:
                self.log(f"❌ Ошибка: {e}", tag="error")
            finally:
                if self._cancel_download and zip_path and os.path.exists(zip_path):
                    os.remove(zip_path)
                self.after(0, lambda: self._end_operation(name))

        threading.Thread(target=_download, daemon=True).start()

    def _kill_process_on_port(self, port):
        if PSUTIL_AVAILABLE:
            for conn in psutil.net_connections(kind='tcp'):
                if conn.laddr and conn.laddr.port == port and conn.status == 'LISTEN':
                    try:
                        pid = conn.pid
                        if pid:
                            p = psutil.Process(pid)
                            self.log(f"🛑 Завершение процесса {p.name()} (PID {pid}), занимающего порт {port}", tag="warn")
                            p.kill()
                            return True
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
        try:
            output = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                                    startupinfo=self._hidden_startupinfo()).stdout
            for line in output.splitlines():
                if f":{port}" in line and "LISTENING" in line:
                    parts = line.split()
                    pid = int(parts[-1])
                    subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True,
                                   startupinfo=self._hidden_startupinfo())
                    self.log(f"🛑 Завершён процесс (PID {pid}) с портом {port}", tag="warn")
                    return True
        except Exception as e:
            self.log(f"⚠ Не удалось освободить порт {port}: {e}", tag="warn")
        return False

    def on_build_select(self, event):
        selected = self.tree.selection()
        if not selected:
            self._set_buttons_state("disabled")
            return

        name = selected[0]
        operation_running = self._operation_lock
        active_operation_name = next(iter(self._active_operations), None) if self._active_operations else None
        status = self.get_build_status(name)
        running = self._is_game_running(name)
        # Если выполняется другая операция, разрешаем только запуск установленных сборок
        if operation_running and name != active_operation_name:
            self._set_buttons_state("disabled")  # отключаем все кнопки
            if status == "installed":
                # Разрешаем запуск и открытие папок
                self.btn_run.config(text="Запустить", state="normal", command=self.toggle_game)
                self.btn_open_folder.config(state="normal")
                self.btn_open_upload.config(state="normal")
            else:
                self.btn_run.config(text="Запустить (Serv+Client)", state="disabled")
            return

        install_text = "Установить"
        install_state = "disabled"
        install_cmd = self.start_installation

        run_text = "Запустить (Serv+Client)"
        run_state = "disabled"
        run_cmd = self.toggle_game

        open_folder_state = "disabled"
        reinstall_state = "disabled"
        delete_state = "disabled"
        clean_rebuild_state = "disabled"
        clean_rebuild_text = "Очистить кэш и пересобрать"
        clean_rebuild_cmd = self.clean_rebuild

        if status in self.BUSY_STATUSES:
            install_text = "Установить"
            install_state = "disabled"
            cancelable = status in (
                "Клонирование...", "Сборка...", "Очистка кэша...", "Переустановка...",
                "Обновление...", "Загрузка готовой сборки..."
            )
            if cancelable:
                run_text = "Отменить"
                run_state = "normal"
                run_cmd = lambda n=name: self.stop_operation(n)
            else:
                run_text = "Запустить (Serv+Client)"
                run_state = "disabled"

        elif running:
            install_text = "Запустить ещё"
            install_state = "normal"
            install_cmd = self.toggle_game
            run_text = "Остановить сборку"
            run_state = "normal"
            run_cmd = self.stop_selected_build
            open_folder_state = "normal"

        elif status == "installed":
            install_text = "Установить"
            install_state = "disabled"
            run_text = "Запустить"
            run_state = "normal"
            run_cmd = self.toggle_game
            open_folder_state = "normal"
            reinstall_state = "normal"
            delete_state = "normal"
            build_path = os.path.join(self.builds_dir, name)
            if os.path.exists(os.path.join(build_path, ".git")):
                clean_rebuild_text = "Обновить"
                clean_rebuild_state = "normal"
                clean_rebuild_cmd = lambda n=name: self.update_build(n)

        elif status in ("partial_build", "clone_incomplete"):
            install_text = "Установить"
            install_state = "disabled"
            run_text = "Запустить (Serv+Client)"
            run_state = "disabled"
            open_folder_state = "normal"
            reinstall_state = "normal"
            delete_state = "normal"
            clean_rebuild_state = "normal"
            clean_rebuild_cmd = self.clean_rebuild

        elif status == "unknown":
            self.log(f"⚠ Сборка '{name}' находится в неопределённом состоянии. Проверьте папку.", tag="warn")

        else:
            install_text = "Установить"
            install_state = "normal"
            install_cmd = self.start_installation
            run_text = "Установить и запустить"
            run_state = "normal"
            run_cmd = self.toggle_game
            if self.repositories[name].get("prebuilt_url"):
                clean_rebuild_text = "📦 Скачать готовую"
                clean_rebuild_state = "normal"
                clean_rebuild_cmd = lambda n=name: self.download_prebuilt(
                    n, self.repositories[n]["prebuilt_url"]
                )

        self.btn_install.config(text=install_text, state=install_state, command=install_cmd)
        self.btn_run.config(text=run_text, state=run_state, command=run_cmd)

        theme = self.THEMES.get(self.settings.get("theme", "Стандартная"))
        if run_text in ("Остановить сборку", "Отменить"):
            run_semantic = "danger"
        else:
            run_semantic = "accent"
        self.btn_run.configure(
            bg=theme[f"btn_{run_semantic}_bg"],
            fg=theme[f"btn_{run_semantic}_fg"],
            activebackground=theme["menu_active_bg"],
            activeforeground=theme["menu_active_fg"],
        )
        self.btn_open_folder.config(state=open_folder_state)
        self.btn_open_upload.config(state=open_folder_state)
        self.btn_reinstall.config(state=reinstall_state)
        self.btn_delete.config(state=delete_state)
        self.btn_clean_rebuild.config(text=clean_rebuild_text, state=clean_rebuild_state, command=clean_rebuild_cmd)

    def _set_buttons_state(self, state):
        for btn in [self.btn_install, self.btn_run, self.btn_open_folder,
                    self.btn_open_upload, self.btn_reinstall,
                    self.btn_delete, self.btn_clean_rebuild]:
            btn.config(state=state)

    def _start_operation(self, name, operation_text, progress_mode="indeterminate"):
        self._cancel_download = False
        if self._operation_lock:
            self.log("⚠ Уже выполняется другая операция. Дождитесь завершения.", tag="warn")
            return
        ...
        if name in self._active_operations:
            self.log(f"⚠ Операция '{operation_text}' уже выполняется для '{name}'.", tag="warn")
            return
        self._operation_lock = True
        self._set_operation(name, operation_text)
        # Больше НЕ отключаем все кнопки и НЕ запрещаем выбор строк
        if progress_mode == "indeterminate":
            self.progress_bar.config(mode="indeterminate")
            self.progress_bar.start()
        else:
            self.progress_bar.config(mode="determinate")
            self.progress_var.set(0)
        self.log(f"▶ {operation_text}", tag="operation")
        self._check_disk_space()

    def delete_build(self):
        name = self._get_selected_name()
        if not name:
            return
        if self._is_game_running(name):
            self._stop_game(name)
            time.sleep(0.5)  # можно уменьшить до 0.2

        if self.settings.get("confirm_destructive", True):
            if not messagebox.askyesno("Подтверждение",
                                       f"Удалить '{name}' полностью?\nВсе файлы будут удалены безвозвратно."):
                return

        self._start_operation(name, "Удаление...")
        self.log(f"🗑 Удаление сборки {name}...", tag="warn")
        build_path = Path(self.builds_dir) / name

        def _del():
            try:
                # Сохраняем .git только если включено в настройках
                if self.settings.get("enable_git_cache", True):
                    self._move_git_to_cache(name, build_path)
                # Полное удаление
                if self._fast_remove_folder(build_path, name):
                    self.log(f"✅ Сборка {name} удалена.", tag="success")
                    self.show_notification("Готово", f"Сборка '{name}' удалена.")
            finally:
                self.after(0, lambda: self._end_operation(name))

        threading.Thread(target=_del, daemon=True).start()

    def _get_git_cache_dir(self):
        return Path(self.builds_dir) / ".git_cache"

    def _move_git_to_cache(self, name, build_path):
        """Перемещает .git папку сборки в кэш (быстро)."""
        git_dir = Path(build_path) / ".git"
        if not git_dir.exists():
            return
        cache_dir = self._get_git_cache_dir() / name
        try:
            # Быстро удаляем старый кэш, если он есть (игнорируя ошибки)
            if cache_dir.exists():
                if sys.platform == "win32":
                    subprocess.run(["cmd", "/c", "rmdir", "/s", "/q", str(cache_dir)],
                                   capture_output=True, timeout=10)
                else:
                    shutil.rmtree(cache_dir, ignore_errors=True)
            # Мгновенное перемещение .git в кэш
            shutil.move(str(git_dir), str(cache_dir))
            self.log(f"💾 Git-кэш для '{name}' перемещён.", tag="info")
        except Exception as e:
            self.log(f"⚠ Не удалось переместить git-кэш: {e}", tag="warn")

    def _move_to_trash(self, folder_path, name):
        if isinstance(folder_path, str):
            folder_path = Path(folder_path)
        self.kill_processes_locking_folder(str(folder_path))

        trash_dir = Path(self.builds_dir) / ".trash"
        trash_dir.mkdir(exist_ok=True)

        timestamp = time.strftime("%Y%m%d_%H%M%S")
        dest = trash_dir / f"{name}_{timestamp}"

        try:
            shutil.move(str(folder_path), str(dest))
            if dest.exists():
                return True
        except Exception as e:
            self.log(f"⚠ Не удалось переместить в корзину: {e}", tag="warn")
        return False

    def reinstall_build(self):
        name = self._get_selected_name()
        if not name:
            return
        if self._is_game_running(name):
            self._stop_game(name)
            time.sleep(0.5)
        build_path = os.path.join(self.builds_dir, name)
        if self.settings.get("confirm_destructive", True):
            if not messagebox.askyesno("Подтверждение", f"Переустановить '{name}'?"):
                return
        self._start_operation(name, "Переустановка...")

        def _reinstall():
            try:
                if os.path.exists(build_path):
                    self._fast_remove_folder(build_path, name)
                self.after(0, lambda: self._end_operation(name))
                self.show_notification("Переустановка", f"Старые файлы '{name}' удалены, начинается установка.")
                self.after(500, self.start_installation)
            except Exception as e:
                self.log(f"❌ Ошибка переустановки: {e}", tag="error")
                self.after(0, lambda: self._end_operation(name))

        threading.Thread(target=_reinstall, daemon=True).start()

    def clean_rebuild(self):
        name = self._get_selected_name()
        if not name:
            return

        build_path = os.path.join(self.builds_dir, name)
        if not os.path.exists(os.path.join(build_path, ".git")):
            messagebox.showwarning("Ошибка", "Это не git-репозиторий. Сборка невозможна.")
            return

        required_projects = [
            os.path.join(build_path, "Content.Server", "Content.Server.csproj"),
            os.path.join(build_path, "Content.Client", "Content.Client.csproj")
        ]
        missing = [p for p in required_projects if not os.path.exists(p)]
        if missing:
            messagebox.showwarning("Ошибка", "Репозиторий повреждён или имеет нестандартную структуру.\n"
                                             "Выполните переустановку сборки.")
            return

        mode = self.repositories[name].get("mode", "Debug")
        if self.settings.get("confirm_clean_rebuild", False):
            if not messagebox.askyesno("Очистить кэш и пересобрать",
                                       f"Будет выполнена глубокая очистка (bin, obj) и пересборка в режиме {mode} для '{name}'."):
                return

        self._start_operation(name, "Очистка кэша...")
        self.clear_console()
        self.log(f"=== Глубокая очистка и пересборка: {name} ===", tag="info")

        def _clean():
            try:
                self._clean_rebuild_thread(name, build_path, is_auto=False)
                self.show_notification("Готово", f"Кэш '{name}' очищен и сборка пересобрана.")
            finally:
                self.after(0, lambda: self._end_operation(name))

        threading.Thread(target=_clean, daemon=True).start()

    def toggle_game(self):
        if self._game_toggle_lock:
            return
        self._game_toggle_lock = True
        self.after(2000, self._unlock_game_toggle)

        name = self._get_selected_name()
        if not name:
            self._game_toggle_lock = False
            return

        status = self.get_build_status(name)
        if status == "installed":
            self._start_game(name)
        elif status == "missing":
            self.log(f"⚠ Сборка '{name}' не установлена. Начинаю установку...", tag="warn")
            self.start_installation(auto_start=True)
        else:
            self.log(f"❌ Сборка '{name}' в состоянии '{status}'. Сначала исправьте её.", tag="error")

    def _unlock_game_toggle(self):
        self._game_toggle_lock = False

    def _start_game(self, name):
        current_count = sum(
            1 for i in self._instances.values()
            if i["name"] == name and (
                    (i["srv"] is not None and i["srv"].poll() is None) or
                    (i["cli"] is not None and i["cli"].poll() is None)
            )
        )
        max_inst = self.settings.get("max_instances", 5)
        if current_count >= max_inst:
            self.log(f"⚠ Достигнут лимит экземпляров ({max_inst}) для '{name}'.", tag="warn")
            messagebox.showinfo("Лимит экземпляров", f"Нельзя запустить более {max_inst} экземпляров одновременно.")
            return

        build_path = os.path.join(self.builds_dir, name)
        server_exe = None
        client_exe = None
        for s, c in self._find_executables(build_path):
            if os.path.exists(s) and server_exe is None:
                server_exe = s
            if os.path.exists(c) and client_exe is None:
                client_exe = c

        if not server_exe and not client_exe:
            self.log("❌ Исполняемые файлы не найдены.", tag="error")
            return

        existing_server = None
        existing_port = None
        for inst in self._instances.values():
            if inst["name"] == name and inst.get("srv") is not None and inst["srv"].poll() is None:
                existing_server = inst["srv"]
                existing_port = inst.get("port")
                break

        self._cleanup_broken_port_config(build_path)

        if existing_server is not None and existing_port:
            port = existing_port
            self.log(f"ℹ Для '{name}' используем порт уже запущенного сервера: {port}", tag="info")
            need_server = False
        else:
            port = self._allocate_port()
            if port is None:
                self.log(f"❌ Не удалось найти свободный UDP-порт для '{name}'.", tag="error")
                return
            self.log(f"🔄 Для '{name}' выбран свободный порт {port}.", tag="info")
            need_server = server_exe is not None

        self.repositories[name]["port"] = port
        self.save_config()

        counter = self._instance_counter.get(name, 0) + 1
        self._instance_counter[name] = counter
        instance_id = f"{name} #{counter}"

        srv_proc = None
        cli_proc = None
        threads = []

        if need_server:
            server_data_dir = os.path.join(build_path, "data", "server")
            os.makedirs(server_data_dir, exist_ok=True)
            srv_args = [
                server_exe,
                "--cvar", f"net.port={port}",
                "--data-dir", server_data_dir,
            ]
            try:
                srv_proc = subprocess.Popen(srv_args, cwd=os.path.dirname(server_exe),
                                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                            stdin=subprocess.PIPE,
                                            text=True, encoding="utf-8", errors="replace",
                                            startupinfo=self._hidden_startupinfo())
                threads.append(threading.Thread(target=self._read_process_output,
                                                args=(srv_proc, "Сервер", "server", instance_id),
                                                daemon=True))
            except Exception as e:
                self.log(f"❌ Ошибка запуска сервера: {e}", tag="error")
                self._instance_counter[name] = counter - 1
                self._release_port(port)
                return

        if client_exe:
            cli_args = [
                client_exe,
                "--launcher",
                "--username", f"Player{counter}",
                "--connect-address", f"udp://127.0.0.1:{port}",
            ]
            try:
                cli_proc = subprocess.Popen(cli_args, cwd=os.path.dirname(client_exe),
                                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                            stdin=subprocess.PIPE,
                                            text=True, encoding="utf-8", errors="replace",
                                            startupinfo=self._hidden_startupinfo())
                threads.append(threading.Thread(target=self._read_process_output,
                                                args=(cli_proc, "Клиент", "client", instance_id),
                                                daemon=True))
            except Exception as e:
                self.log(f"❌ Ошибка запуска клиента: {e}", tag="error")
                if srv_proc:
                    srv_proc.terminate()
                self._instance_counter[name] = counter - 1
                self._release_port(port)
                return

        if not srv_proc and not cli_proc:
            self._instance_counter[name] = counter - 1
            self._release_port(port)
            return

        for t in threads:
            t.start()

        self._instances[instance_id] = {
            "name": name,
            "srv": srv_proc,
            "cli": cli_proc,
            "port": port,
            "owns_port": srv_proc is not None,
            "threads": threads,
            "log_buffer": deque(maxlen=10000)
        }
        self._current_instance_id = instance_id
        self._refresh_console_view()
        self._refresh_instance_list()
        self.refresh_builds_list()
        self.tree.selection_set(name)
        self.tree.see(name)
        self.on_build_select(None)
        self._check_game_processes(instance_id)

    def _refresh_console_view(self):
        self.console.config(state="normal")
        self.console.delete("1.0", "end")

        if self._current_instance_id and self._current_instance_id in self._instances:
            buffer = self._instances[self._current_instance_id]["log_buffer"]
        else:
            buffer = self._log_history

        for text, tag in list(buffer)[-500:]:
            category = self._get_tag_category(tag)
            if self.log_filters.get(category, True):
                self.console.insert("end", text + "\n", tag)

        self.console.see("end")
        self.console.config(state="disabled")

    def _stop_instance(self, instance_id):
        if instance_id not in self._instances:
            return
        inst = self._instances[instance_id]
        name = inst["name"]
        had_server = inst.get("srv") is not None and inst["srv"].poll() is None
        port = inst.get("port")

        if had_server:
            client_instances = [
                iid for iid, i in self._instances.items()
                if i["name"] == name and iid != instance_id
                   and i.get("cli") is not None and i["cli"].poll() is None
            ]
            for cid in client_instances:
                self._stop_instance(cid)

        for p in (inst.get("srv"), inst.get("cli")):
            if p is not None and p.poll() is None:
                try:
                    p.terminate()
                    p.wait(timeout=2)
                except:
                    try:
                        p.kill()
                    except:
                        pass

        for t in inst["threads"]:
            if t.is_alive():
                t.join(timeout=1)

        self.log(f"🛑 Экземпляр {instance_id} остановлен.", tag="warn")
        self._instances.pop(instance_id, None)

        if inst.get("owns_port"):
            self._release_port(port)
            other_server_alive = any(
                i.get("srv") is not None and i["srv"].poll() is None
                for i in self._instances.values() if i["name"] == name
            )
            if not other_server_alive and self.repositories.get(name, {}).pop("port", None):
                self.save_config()
                self.log(f"ℹ Порт {port} для '{name}' освобождён.", tag="info")

        if self._current_instance_id == instance_id:
            self._current_instance_id = None

        self.after(0, self._refresh_instance_list)
        self.after(0, self.refresh_builds_list)
        self.after(0, self.on_build_select, None)
        self.after(0, self._refresh_console_view)

    def _read_process_output(self, process, prefix, base_tag, instance_id):
        try:
            for line in process.stdout:
                line = line.strip()
                if not line:
                    continue
                if "[ERRO]" in line or "[FATL]" in line:
                    tag = f"{base_tag}_error"
                elif "[WARN]" in line:
                    tag = f"{base_tag}_warn"
                else:
                    tag = base_tag
                if instance_id in self._instances:
                    self._instances[instance_id]["log_buffer"].append((f"[{prefix}] {line}", tag))
                    if self._current_instance_id == instance_id:
                        self.after(0, self._refresh_console_view)
        except Exception:
            pass
        finally:
            if process.poll() is None:
                process.terminate()

    def open_logs_folder(self):
        log_dir = Path(__file__).parent.parent / "logs"
        log_dir.mkdir(exist_ok=True)
        sys_open_path(log_dir)

    def _stop_game(self, name):
        instances_to_stop = [iid for iid, inst in self._instances.items() if inst["name"] == name]
        if not instances_to_stop:
            return
        self._set_operation(name, "Остановка...")
        self._set_buttons_state("disabled")

        def _stop():
            server_instances = [iid for iid in instances_to_stop
                                if self._instances.get(iid) and self._instances[iid]["srv"] is not None
                                and self._instances[iid]["srv"].poll() is None]
            for iid in server_instances:
                self._stop_instance(iid)
            remaining = [iid for iid in instances_to_stop if iid in self._instances]
            for iid in remaining:
                self._stop_instance(iid)
            if name in self.repositories and "port" in self.repositories[name]:
                del self.repositories[name]["port"]
                self.save_config()
            self.log(f"🛑 Все экземпляры '{name}' остановлены.", tag="warn")
            self.show_notification("Остановлено", f"Все экземпляры '{name}' остановлены.")
            self._end_operation(name)

        threading.Thread(target=_stop, daemon=True).start()

    def _check_game_processes(self, instance_id):
        if instance_id not in self._instances:
            return
        inst = self._instances[instance_id]
        srv_alive = inst["srv"] is not None and inst["srv"].poll() is None
        cli_alive = inst["cli"] is not None and inst["cli"].poll() is None

        if not srv_alive and not cli_alive:
            if inst.get("owns_port"):
                self._release_port(inst.get("port"))
            if self.settings.get("keep_finished_instances", True):
                inst["finished"] = True
                self._refresh_instance_list()
                self.refresh_builds_list()
                self.on_build_select(None)
                self._refresh_console_view()
            else:
                self._stop_instance(instance_id)
            return
        else:
            self.after(2000, lambda: self._check_game_processes(instance_id))

    def start_installation(self, auto_start=False):
        name = self._get_selected_name()
        if not name:
            return
        if name in self._active_operations:
            messagebox.showwarning("Операция уже выполняется", f"Подождите завершения текущей операции для '{name}'.")
            return
        repo_data = self.repositories[name]
        repo_url = repo_data["url"]
        build_path = os.path.join(self.builds_dir, name)
        self._start_operation(name, "Клонирование...", progress_mode="determinate")
        self.clear_console()
        self.log(f"=== Установка: {name} (режим {repo_data.get('mode', 'Debug')}) ===", tag="info")
        threading.Thread(target=self._installation_thread, args=(name, repo_url, build_path, auto_start),
                         daemon=True).start()

    def _installation_thread(self, name, repo_url, build_path, auto_start=False):
        try:
            # ---------- Клонирование ----------
            clone_success = False
            git_cache_path = self._get_git_cache_dir() / name

            # 1) Пытаемся клонировать с git-кэшем, если он есть
            if git_cache_path.exists():
                clone_cmd = ["git", "clone", "--progress",
                             "--reference", str(git_cache_path), "--dissociate"]
                if self.settings.get("shallow_clone", False):
                    clone_cmd += ["--depth", "1"]
                clone_cmd += [repo_url, build_path]

                clone_success = self._run_subprocess(
                    clone_cmd, cwd=None,
                    step_name="git clone (с кэшем)",
                    progress_parser=self.filter_git_line,
                    operation_name=name
                )

                if not clone_success:
                    self.log("⚠ Клонирование с git-кэшем не удалось. Пробуем без кэша...", tag="warn")
                    try:
                        shutil.rmtree(git_cache_path, ignore_errors=True)
                    except Exception:
                        pass

            # Если операция отменена после попытки с кэшем — выходим
            if self._cancel_download:
                self.log("🛑 Установка отменена пользователем.", tag="warn")
                self.after(0, lambda: self._end_operation(name))
                self.after(0, self._install_failed, name, build_path)
                return

            # 2) Если с кэшем не получилось, клонируем обычным способом
            if not clone_success:
                clone_cmd = ["git", "clone", "--progress"]
                if self.settings.get("shallow_clone", False):
                    clone_cmd += ["--depth", "1"]
                clone_cmd += [repo_url, build_path]

                clone_success = self._run_subprocess(
                    clone_cmd, cwd=None,
                    step_name="git clone",
                    progress_parser=self.filter_git_line,
                    operation_name=name
                )

            if not clone_success:
                self.after(0, lambda: self._end_operation(name))
                self.after(0, self._install_failed, name, build_path)
                return

            # Проверка отмены после клонирования
            if self._cancel_download:
                self.log("🛑 Установка отменена после клонирования.", tag="warn")
                self.after(0, lambda: self._end_operation(name))
                self.after(0, self._install_failed, name, build_path)
                return

            # После успешного клонирования обновляем прогресс
            self.after(0, self.progress_var.set, 100)
            self.after(0, self.lbl_speed.config, {"text": "Скачано"})

            # ---------- Подготовка / RUN_THIS.py / сабмодули ----------
            if self._cancel_download:
                self.log("🛑 Установка отменена перед выполнением RUN_THIS.py.", tag="warn")
                self.after(0, lambda: self._end_operation(name))
                self.after(0, self._install_failed, name, build_path)
                return

            self._set_operation(name, "Сборка...")
            self.after(0, self.progress_bar.config, {"mode": "indeterminate"})
            self.after(0, self.progress_bar.start)
            self.after(0, self.lbl_speed.config, {"text": "Сборка..."})

            if not self._run_subprocess([sys.executable, "RUN_THIS.py"], build_path,
                                        "RUN_THIS.py", operation_name=name):
                self.log("⚠ RUN_THIS.py не выполнен. Пробуем git submodule update...", tag="warn")
                self._run_subprocess(["git", "submodule", "update", "--init", "--recursive"],
                                     build_path, "git submodule update", operation_name=name)

            # Проверка отмены после RUN_THIS.py / сабмодулей
            if self._cancel_download:
                self.log("🛑 Установка отменена после подготовки.", tag="warn")
                self.after(0, lambda: self._end_operation(name))
                self.after(0, self._install_failed, name, build_path)
                return

            # ---------- Проверка целостности репозитория ----------
            required_files = [
                os.path.join(build_path, "Content.Server", "Content.Server.csproj"),
                os.path.join(build_path, "Content.Client", "Content.Client.csproj"),
                os.path.join(build_path, "Content.Shared", "Content.Shared.csproj")
            ]
            missing = [f for f in required_files if not os.path.exists(f)]
            if missing:
                self.log("❌ Клонирование выполнено, но отсутствуют важные файлы проекта:", tag="error")
                for f in missing:
                    self.log(f"   - {f}", tag="error")
                self.log("Возможно, репозиторий имеет нестандартную структуру или клонирование было прервано.",
                         tag="warn")
                self.after(0, lambda: self._end_operation(name))
                self.after(0, self._install_failed, name, build_path)
                return

            # ---------- Проверка global.json и SDK ----------
            global_json = os.path.join(build_path, "global.json")
            if os.path.exists(global_json):
                try:
                    with open(global_json, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    req_sdk = data.get("sdk", {}).get("version")
                    if req_sdk:
                        installed = self._get_installed_sdks()
                        if req_sdk not in installed:
                            if self._offer_sdk_install_before_build(req_sdk, name, build_path):
                                self.after(0, lambda: self._end_operation(name))
                                self.after(0, self._install_failed, name, build_path)
                                return
                            else:
                                self.log(f"⚠ Сборка '{name}' отменена, требуется SDK {req_sdk}.", tag="warn")
                                self.after(0, lambda: self._end_operation(name))
                                self.after(0, self._install_failed, name, build_path)
                                return
                        self._fix_dotnet_sdk(global_json)
                except Exception:
                    pass

            # ---------- Сборка ----------
            if self._cancel_download:
                self.log("🛑 Установка отменена перед сборкой.", tag="warn")
                self.after(0, lambda: self._end_operation(name))
                self.after(0, self._install_failed, name, build_path)
                return

            mode = self.repositories[name].get("mode", "Debug")
            self._print_build_diagnostics(build_path)
            self._run_pre_restore_if_needed(build_path)
            build_cmd = self._get_build_command(mode)
            self.log(f"--- dotnet build ({mode}) ---", tag="info")

            if self._run_subprocess(build_cmd, build_path, "dotnet build", operation_name=name):
                self.after(0, lambda: self._end_operation(name))
                self.after(0, self._install_success, name)
                if auto_start:
                    self.after(500, lambda: self._start_game(name))
            else:
                self.after(0, self._handle_build_failure, name, build_path, is_clean_rebuild=False)

        except Exception as e:
            self.log(f"❌ Исключение в установке: {e}", tag="error")
            self.after(0, lambda: self._end_operation(name))
            self.after(0, self._install_failed, name, build_path)

    def _get_installed_sdks(self):
        try:
            res = subprocess.run(["dotnet", "--list-sdks"], capture_output=True, text=True, timeout=5,
                                 startupinfo=self._hidden_startupinfo())
            return re.findall(r'^(\d+\.\d+\.\d+)', res.stdout, re.MULTILINE)
        except Exception:
            return []

    def _get_build_command(self, mode="Debug"):
        cmd = ["dotnet", "build"]
        if self.settings.get("parallel_build", False):
            cmd.append("-m")
        if mode == "Release":
            cmd += ["-c", "Release"]
        return cmd

    def _run_pre_restore_if_needed(self, build_path):
        if self.settings.get("pre_restore", False):
            self.log("Выполняется предварительное восстановление пакетов (dotnet restore)...", tag="info")
            if not self._run_subprocess(["dotnet", "restore"], build_path, "dotnet restore"):
                self.log("⚠ Ошибка восстановления пакетов.", tag="warn")

    def _continue_build(self, name, build_path):
        mode = self.repositories[name].get("mode", "Debug")
        self._print_build_diagnostics(build_path)
        self._run_pre_restore_if_needed(build_path)
        build_cmd = self._get_build_command(mode)
        self.log(f"--- dotnet build ({mode}) ---", tag="info")
        if self._run_subprocess(build_cmd, build_path, "dotnet build", operation_name=name):
            self.after(0, lambda: self._end_operation(name))
            self.after(0, self._install_success, name)
        else:
            self.after(0, self._handle_build_failure, name, build_path, is_clean_rebuild=False)

    def _handle_build_failure(self, name, build_path, is_clean_rebuild=False):
        self.after(0, self.progress_bar.stop)
        self.after(0, self.progress_bar.config, {"mode": "determinate"})
        self.after(0, self.progress_var.set, 0)
        self.after(0, self.lbl_speed.config, {"text": "Ошибка"})
        self.log("❌ Сборка не удалась.", tag="error")
        self.show_notification("Ошибка сборки", f"Сборка '{name}' не удалась.")

        if not is_clean_rebuild:
            self.log("💡 Пробуем очистить кэш и пересобрать автоматически...", tag="bold")
            self._set_operation(name, "Авто-пересборка...")
            self._clean_rebuild_thread(name, build_path, is_auto=True)
            return

        nuget_errors = any("NU1301" in line and "pkgs.dev.azure.com" in line for line in
                           self.console.get("1.0", "end").splitlines())
        if nuget_errors:
            self.log("⚠ Проблема с NuGet-источником pkgs.dev.azure.com. Отключаю временно.", tag="warn")
            try:
                subprocess.run(["dotnet", "nuget", "disable", "source", "dotnet-eng"],
                               capture_output=True, timeout=10, startupinfo=self._hidden_startupinfo())
                self._nuget_disabled = True
            except Exception:
                pass
            self.log("🔧 Повторная сборка...", tag="bold")
            mode = self.repositories[name].get("mode", "Debug")
            self._run_pre_restore_if_needed(build_path)
            build_cmd = self._get_build_command(mode)
            if self._run_subprocess(build_cmd, build_path, "dotnet build", operation_name=name):
                if self._nuget_disabled:
                    self.log("✅ Сборка успешна. Чтобы включить источник обратно: dotnet nuget enable source dotnet-eng",
                             tag="success")
                self.after(0, lambda: self._end_operation(name))
                self.after(0, self._install_success, name)
                return
            else:
                self.log("❌ Повторная сборка также не удалась.", tag="error")

        self.log("💡 Рекомендации:", tag="bold")
        self.log("   1. Проверьте интернет-соединение.", tag="info")
        self.log("   2. Попробуйте очистить кэш и пересобрать вручную.", tag="info")
        self.log("   3. Убедитесь, что репозиторий не содержит ошибок.", tag="info")
        self.after(0, lambda: self._end_operation(name))
        self.after(0, self._install_failed, name, build_path)

    def _prompt_install_missing_sdk(self, required_version, build_name, build_path):
        if messagebox.askyesno("Установка .NET SDK",
                               f"Программа может автоматически скачать и запустить установщик .NET SDK {required_version}.\n\n"
                               "Продолжить?"):
            self._download_and_install_sdk(required_version, build_name, build_path)
        else:
            self.after(0, lambda: self._end_operation(build_name))
            self.after(0, self._install_failed, build_name, build_path)

    def _get_dotnet_sdk_url(self, version):
        arch = platform.machine().lower()
        if arch in ("arm64", "aarch64"):
            win_arch = "arm64"
        elif arch in ("x86_64", "amd64"):
            win_arch = "x64"
        else:
            win_arch = "x86"
        return f"https://dotnetcli.azureedge.net/dotnet/Sdk/{version}/dotnet-sdk-{version}-win-{win_arch}.exe"

    def _download_and_install_sdk(self, version, build_name, build_path):
        url = self._get_dotnet_sdk_url(version)
        self.log(f"⬇ Начинаю загрузку .NET SDK {version}...", tag="bold")
        self._start_operation(build_name or "system", "Загрузка SDK...", progress_mode="determinate")

        def download_thread():
            try:
                self._last_download_log = -1
                self._download_start = time.time()
                installer_path = self.download_manager.download(
                    url, dest_name=f"dotnet-sdk-{version}-{platform.machine().lower()}.exe",
                    progress_callback=self._download_progress
                )
                if not installer_path:
                    raise Exception("Не удалось скачать SDK")

                ps_path = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
                if not os.path.exists(ps_path):
                    ps_path = "powershell.exe"
                ps_args = [ps_path, "-Command",
                           f'Start-Process -FilePath "{installer_path}" -Verb RunAs -Wait']
                self.log(f"🔧 Запуск установщика .NET SDK {version}...", tag="bold")
                result = subprocess.run(ps_args, startupinfo=self._hidden_startupinfo(),
                                        capture_output=True, text=True)
                if result.returncode != 0:
                    self.log(f"❌ Установка .NET SDK {version} не была завершена (код {result.returncode}). "
                             f"Возможно, отменён запрос UAC.", tag="error")
                    return
                self.log(f"⏳ Установка .NET SDK {version} завершена.", tag="bold")

                installed = self._get_installed_sdks()
                if version not in installed:
                    self.log(f"⚠ Версия {version} не обнаружена после установки. "
                             f"Возможно, требуется перезапуск менеджера или вручную обновить PATH.", tag="warn")
                else:
                    self.log(f"✅ .NET SDK {version} успешно установлена.", tag="success")
                    for repo_name in self.repositories:
                        bp = os.path.join(self.builds_dir, repo_name)
                        gj = os.path.join(bp, "global.json")
                        if os.path.exists(gj):
                            self._fix_dotnet_sdk(gj)

                self.log("💡 Для обновления системного PATH может потребоваться перезапуск менеджера.", tag="info")

            except Exception as e:
                self.log(f"❌ Ошибка при работе с .NET SDK: {e}", tag="error")
            finally:
                if build_name:
                    self.after(0, lambda: self._end_operation(build_name))
                else:
                    self._end_operation("system")

        threading.Thread(target=download_thread, daemon=True).start()

    def _download_progress(self, block_num, block_size, total_size):
        if total_size > 0:
            percent = min(100, int(block_num * block_size * 100 / total_size))
            self.after(0, self.progress_var.set, percent)

            elapsed = time.time() - self._download_start
            if elapsed > 0:
                speed = block_num * block_size / elapsed
                self.after(0, self.lbl_speed.config, {"text": f"{speed / 1024 / 1024:.2f} MiB/s"})

            # Логируем каждые 10% (и 100%)
            if percent % 10 == 0 and percent != self._last_download_log:
                self.log(f"⬇ Загрузка: {percent}%", tag="info")
                self._last_download_log = percent
        else:
            self.after(0, self.progress_bar.config, {"mode": "indeterminate"})
            self.after(0, self.progress_bar.start)

    def _print_build_diagnostics(self, build_path):
        try:
            ver = subprocess.run(["dotnet", "--version"], capture_output=True, text=True, timeout=5,
                                 startupinfo=self._hidden_startupinfo()).stdout.strip()
            self.log(f"Текущая версия .NET SDK: {ver}", tag="info")
        except:
            pass
        gj = os.path.join(build_path, "global.json")
        if os.path.exists(gj):
            try:
                with open(gj, "r") as f:
                    data = json.load(f)
                    self.log(f"global.json: {json.dumps(data, indent=2)}", tag="info")
            except:
                pass
        self.log(f"Платформа: {sys.platform}, архитектура: {('x64' if sys.maxsize > 2 ** 32 else 'x86')}",
                 tag="info")

    def _run_subprocess(self, cmd, cwd, step_name, progress_parser=None, operation_name=None):
        try:
            process = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       text=True, encoding="utf-8", errors="replace",
                                       startupinfo=self._hidden_startupinfo())
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
                # Если операция отменена, прерываем процесс
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
        except Exception:
            pass

        process.wait(timeout=1800)
        if process in self._running_subprocesses:
            self._running_subprocesses.remove(process)
        if operation_name and process in self._operation_procs.get(operation_name, []):
            self._operation_procs[operation_name].remove(process)

        if process.returncode != 0:
            self.log(f"❌ {step_name} ошибка {process.returncode}", tag="error")
            return False
        return True

        process.wait(timeout=1800)
        if process in self._running_subprocesses:
            self._running_subprocesses.remove(process)
        if operation_name and process in self._operation_procs.get(operation_name, []):
            self._operation_procs[operation_name].remove(process)

        if process.returncode != 0:
            self.log(f"❌ {step_name} ошибка {process.returncode}", tag="error")
            return False
        return True

    def _install_success(self, name):
        self.progress_bar.stop()
        self.progress_bar.config(mode="determinate")
        self.progress_var.set(100)
        self.lbl_speed.config(text="Готово")
        self.log("=== Установка успешно завершена ===", tag="done")
        self.show_notification("Установка завершена", f"Сборка '{name}' успешно установлена.")
        self.tree.config(selectmode="browse")
        self.refresh_builds_list()
        self.tree.selection_set(name)
        self.tree.see(name)
        self.on_build_select(None)

    def _install_failed(self, name, build_path):
        self.progress_bar.stop()
        self.progress_bar.config(mode="determinate")
        self.progress_var.set(0)
        self.lbl_speed.config(text="Ошибка")
        client_found = False
        server_found = False
        for s, c in self._find_executables(build_path):
            if os.path.exists(s):
                server_found = True
            if os.path.exists(c):
                client_found = True
        if server_found:
            self.log("✅ Серверная часть собрана.", tag="success")
        if client_found:
            self.log("✅ Клиентская часть собрана.", tag="success")
        if not client_found and not server_found:
            self.log("Ни один исполняемый файл не создан.", tag="warn")
        self.after(0, lambda: self._ask_delete_failed(name, build_path))

    def _ask_delete_failed(self, name, build_path):
        if self.settings.get("auto_delete_failed", False):
            client_found = any(os.path.exists(s) for s, _ in self._find_executables(build_path))
            server_found = any(os.path.exists(c) for _, c in self._find_executables(build_path))
            if not client_found and not server_found:
                threading.Thread(target=self._fast_remove_folder, args=(build_path, name), daemon=True).start()
            else:
                self.log("⚠ Сборка частично удалась. Файлы оставлены для возможного запуска.", tag="warn")
        else:
            self.log("ℹ Сборка не удалена. Папка сохранена для возможного повторного использования.", tag="info")
        self.tree.config(selectmode="browse")
        self.refresh_builds_list()
        self._reenable_buttons()

    def _reenable_buttons(self):
        self._set_buttons_state("normal")
        self.tree.config(selectmode="browse")
        self.on_build_select(None)

    def open_build_folder(self):
        name = self._get_selected_name()
        if name:
            build_path = os.path.join(self.builds_dir, name)
            sys_open_path(build_path)

    def kill_processes_locking_folder(self, folder_path):
        killed = False
        normalized = os.path.normpath(folder_path).lower()
        if PSUTIL_AVAILABLE:
            for proc in psutil.process_iter(['pid', 'name', 'exe', 'cwd']):
                try:
                    exe = proc.info['exe']
                    if exe and os.path.normpath(exe).lower().startswith(normalized):
                        self.log(f"🛑 Завершение {proc.info['name']} (PID {proc.info['pid']})", tag="warn")
                        proc.kill()
                        killed = True
                        continue
                    cwd = proc.info['cwd']
                    if cwd and os.path.normpath(cwd).lower().startswith(normalized):
                        self.log(f"🛑 Завершение {proc.info['name']} (PID {proc.info['pid']}) по cwd", tag="warn")
                        proc.kill()
                        killed = True
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        else:
            # Быстрый способ: использовать taskkill с фильтром по модулю (git, dotnet и т.п.)
            try:
                # Убиваем все процессы git, которые могут держать файлы
                subprocess.run(["taskkill", "/F", "/IM", "git.exe"], capture_output=True, timeout=5)
                subprocess.run(["taskkill", "/F", "/IM", "dotnet.exe"], capture_output=True, timeout=5)
                killed = True
                self.log("🛑 Процессы git/dotnet завершены через taskkill.", tag="warn")
            except Exception as e:
                self.log(f"⚠ Не удалось завершить процессы: {e}", tag="warn")

        if killed:
            time.sleep(0.2)  # уменьшили с 1 секунды до 0.2
        return killed

    def _fast_remove_folder(self, folder_path, name):
        if isinstance(folder_path, str):
            folder_path = Path(folder_path)
        self.kill_processes_locking_folder(str(folder_path))

        # Быстрое удаление через cmd
        if sys.platform == "win32":
            try:
                subprocess.run(["cmd", "/c", "rmdir", "/s", "/q", str(folder_path)],
                               capture_output=True, timeout=10)
                if not folder_path.exists():
                    self.log(f"✅ Папка {name} удалена через cmd.", tag="success")
                    return True
            except subprocess.TimeoutExpired:
                pass

        # Если не получилось, пробуем shutil с ignore_errors
        try:
            shutil.rmtree(str(folder_path), ignore_errors=True)
            if not folder_path.exists():
                self.log(f"✅ Папка {name} удалена через shutil.", tag="success")
                return True
        except Exception:
            pass

        # Последний шанс – от имени администратора
        if sys.platform == "win32":
            ps_command = (
                f'Start-Process cmd -ArgumentList "/c", "rmdir", "/s", "/q", '
                f'"{str(folder_path)}" -Verb RunAs'
            )
            try:
                subprocess.Popen(["powershell", "-Command", ps_command], shell=True)
                self.after(1000, lambda: self._check_removed(str(folder_path), name))
            except Exception as e:
                self.log(f"❌ Ошибка повышения: {e}", tag="error")
        return False

    def _check_removed(self, folder_path, name):
        if not os.path.exists(folder_path):
            self.log(f"✅ Папка {name} удалена администратором.", tag="success")
        else:
            self.log(f"❌ Папка {name} всё ещё существует.", tag="error")

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
        except Exception:
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

    def _clean_rebuild_thread(self, name, build_path, is_auto=False):
        mode = self.repositories[name].get("mode", "Debug")

        required_projects = [
            os.path.join(build_path, "Content.Server", "Content.Server.csproj"),
            os.path.join(build_path, "Content.Client", "Content.Client.csproj")
        ]
        if any(not os.path.exists(p) for p in required_projects):
            self.log("❌ Отсутствуют ключевые проекты. Пропускаем очистку и сборку.", tag="error")
            self.after(0, self._handle_build_failure, name, build_path, is_clean_rebuild=True)
            return

        self._run_subprocess(["dotnet", "clean"], build_path, "dotnet clean", operation_name=name)

        for root, dirs, files in os.walk(build_path):
            for d in dirs:
                if d.lower() in ("bin", "obj"):
                    full = os.path.join(root, d)
                    try:
                        shutil.rmtree(full)
                        self.log(f"  Удалено {full}", tag="info")
                    except Exception as e:
                        self.log(f"  Ошибка удаления {full}: {e}", tag="warn")

        global_json = os.path.join(build_path, "global.json")
        if os.path.exists(global_json):
            self._fix_dotnet_sdk(global_json)

        self._run_pre_restore_if_needed(build_path)
        build_cmd = self._get_build_command(mode)

        self.log(f"--- Сборка dotnet build ({mode}) ---", tag="info")
        if self._run_subprocess(build_cmd, build_path, "dotnet build", operation_name=name):
            if is_auto:
                self.after(0, lambda: self._end_operation(name))
            self.after(0, self._install_success, name)
        else:
            self.after(0, self._handle_build_failure, name, build_path, is_clean_rebuild=True)

    def filter_git_line(self, line):
        percent_match = re.search(r'(\d+)%', line)
        if percent_match:
            percent = int(percent_match.group(1))
            self.after(0, self.progress_var.set, percent)

        speed_match = re.search(r'\|\s*([\d.]+\s*[a-zA-Z]+/s)', line)
        if speed_match:
            self.after(0, self.lbl_speed.config, {"text": speed_match.group(1)})
        return line

    def copy_logs(self):
        logs = self.console.get("1.0", "end").strip()
        if logs:
            self.clipboard_clear()
            self.clipboard_append(logs)
            self.btn_copy_logs.config(text="Скопировано!!")
            self.after(2000, lambda: self.btn_copy_logs.config(text="Скопировать логи"))

    def clear_console(self):
        self.console.delete("1.0", "end")
        self.progress_var.set(0)
        self.lbl_speed.config(text="0.00 MiB/s")
        self.progress_bar.config(mode="determinate")

    def check_repository_updates(self, name):
        """Проверяет наличие новых коммитов в удалённом репозитории."""
        build_path = os.path.join(self.builds_dir, name)
        if not os.path.exists(os.path.join(build_path, ".git")):
            self.log(f"❌ '{name}' не является git-репозиторием.", tag="error")
            return

        self.log(f"🔍 Проверка обновлений для '{name}'...", tag="operation")

        def _check():
            try:
                res_local = subprocess.run(["git", "rev-parse", "HEAD"], cwd=build_path,
                                           capture_output=True, text=True, timeout=10)
                if res_local.returncode != 0:
                    raise Exception("Не удалось получить локальный коммит")
                local_commit = res_local.stdout.strip()

                subprocess.run(["git", "fetch"], cwd=build_path, capture_output=True, text=True,
                               timeout=60, startupinfo=self._hidden_startupinfo())

                res_remote = subprocess.run(["git", "rev-parse", "@{u}"], cwd=build_path,
                                            capture_output=True, text=True, timeout=10)
                if res_remote.returncode != 0:
                    raise Exception("Удалённая ветка не найдена")
                remote_commit = res_remote.stdout.strip()

                if local_commit == remote_commit:
                    self.log(f"✅ '{name}' актуальна (нет новых коммитов).", tag="success")
                else:
                    res_count = subprocess.run(
                        ["git", "rev-list", "--count", f"{local_commit}..{remote_commit}"],
                        cwd=build_path, capture_output=True, text=True, timeout=10
                    )
                    count = res_count.stdout.strip()
                    self.log(f"🔄 Для '{name}' доступно обновление ({count} коммитов).", tag="done")
                    if messagebox.askyesno("Доступно обновление",
                                           f"Для сборки '{name}' найдено {count} новых коммитов.\n"
                                           "Хотите обновить её сейчас?"):
                        self.update_build(name)
            except Exception as e:
                self.log(f"❌ Ошибка при проверке обновлений '{name}': {e}", tag="error")

        threading.Thread(target=_check, daemon=True).start()

    def update_build(self, name):
        build_path = os.path.join(self.builds_dir, name)
        if not os.path.exists(os.path.join(build_path, ".git")):
            self.log("❌ Не является git-репозиторием.", tag="error")
            return

        self._start_operation(name, "Обновление...")
        self.log(f"🔄 Обновление '{name}'...", tag="bold")

        def _update():
            try:
                self._run_subprocess(["git", "pull"], build_path, "git pull", operation_name=name)
                self._run_subprocess(["git", "submodule", "update", "--init", "--recursive"], build_path,
                                     "git submodule update", operation_name=name)
                mode = self.repositories[name].get("mode", "Debug")
                self._run_pre_restore_if_needed(build_path)
                build_cmd = self._get_build_command(mode)
                if self._run_subprocess(build_cmd, build_path, "dotnet build", operation_name=name):
                    self.log("✅ Обновление завершено.", tag="done")
                    self.show_notification("Обновление завершено", f"'{name}' обновлена.")
                else:
                    self.log("❌ Ошибка при сборке после обновления.", tag="error")
            except Exception as e:
                self.log(f"❌ Ошибка: {e}", tag="error")
            finally:
                self.after(0, lambda: self._end_operation(name))

        threading.Thread(target=_update, daemon=True).start()

    def apply_theme(self, theme_name):
        t = self.THEMES.get(theme_name, self.THEMES["Стандартная"])
        self.settings["theme"] = theme_name
        self.configure(bg=t["bg"])

        self.menu_bar.configure(bg=t["menu_bg"], highlightbackground=t["menu_highlight"],
                                highlightcolor=t["menu_highlight"])
        self.repo_btn.configure(bg=t["menu_bg"], fg=t["menu_fg"],
                                activebackground=t["menu_active_bg"], activeforeground=t["menu_active_fg"])
        self.settings_btn.configure(bg=t["menu_bg"], fg=t["menu_fg"],
                                    activebackground=t["menu_active_bg"], activeforeground=t["menu_active_fg"],
                                    highlightbackground=t["menu_highlight"], highlightcolor=t["menu_highlight"])

        self.hotbar_frame.configure(bg=t["hotbar_bg"], highlightbackground=t["hotbar_highlight"],
                                    highlightcolor=t["hotbar_highlight"])
        self.lbl_speed.configure(bg=t["hotbar_bg"], fg=t["hotbar_fg"])
        self.btn_copy_logs.configure(bg=t["hotbar_btn_bg"], fg=t["hotbar_btn_fg"],
                                     activebackground=t["menu_active_bg"], activeforeground=t["menu_active_fg"],
                                     highlightbackground=t["menu_highlight"], highlightcolor=t["menu_highlight"])
        self.btn_clear_console.configure(bg=t["hotbar_btn_bg"], fg=t["hotbar_btn_fg"],
                                         activebackground=t["menu_active_bg"], activeforeground=t["menu_active_fg"],
                                         highlightbackground=t["menu_highlight"], highlightcolor=t["menu_highlight"])

        if hasattr(self, 'left_frame'):
            self.left_frame.configure(bg=t["bg"])
        if hasattr(self, 'right_frame'):
            self.right_frame.configure(bg=t["bg"])
        if hasattr(self, 'filter_frame'):
            self.filter_frame.configure(bg=t["bg"])
        if hasattr(self, 'menu_sep1'):
            self.menu_sep1.configure(bg=t["menu_highlight"])
        if hasattr(self, 'menu_sep2'):
            self.menu_sep2.configure(bg=t["menu_highlight"])

        for lbl in [self.lbl_available, self.lbl_actions, self.lbl_instances]:
            lbl.configure(bg=t["left_header_bg"], fg=t["left_header_fg"])

        self.lbl_console_header.configure(bg=t["left_header_bg"], fg=t["left_header_fg"])
        for cb in self.filter_checkbuttons:
            cb.configure(bg=t["left_header_bg"], fg=t["left_header_fg"],
                         selectcolor=t["left_header_bg"],
                         activebackground=t["left_header_bg"], activeforeground=t["left_header_fg"])

        self.console_frame.configure(highlightbackground=t["console_highlight"],
                                     highlightcolor=t["console_highlight"])
        self.console_frame.update_idletasks()

        self.tree_frame.configure(highlightbackground=t["tree_frame_highlight"],
                                  highlightcolor=t["tree_frame_highlight"],
                                  highlightthickness=2)
        self.tree_frame.update_idletasks()
        self.tree_frame.update()

        if hasattr(self, 'instance_frame'):
            self.instance_frame.configure(highlightbackground=t["tree_frame_highlight"],
                                          highlightcolor=t["tree_frame_highlight"])

        style = ttk.Style()

        style.configure(".", background=t["bg"], foreground=t["fg"],
                        fieldbackground=t["tree_bg"], bordercolor=t["bg"],
                        lightcolor=t["bg"], darkcolor=t["bg"])

        style.configure("Treeview",
                        background=t["tree_bg"],
                        fieldbackground=t["tree_bg"],
                        foreground=t["tree_fg"],
                        borderwidth=0,
                        relief="flat")
        style.map("Treeview",
                  background=[("selected", t["tree_sel_bg"])],
                  foreground=[("selected", t["tree_fg"])])
        style.configure("Treeview.Heading",
                        background=t["tree_heading_bg"],
                        foreground=t["tree_heading_fg"],
                        bordercolor=t["tree_frame_highlight"],
                        relief="flat",
                        borderwidth=0)
        style.map("Treeview.Heading",
                  background=[("pressed", t["bg"]), ("active", t["tree_bg"])],
                  foreground=[("pressed", t["menu_highlight"]), ("active", t["tree_fg"])],
                  bordercolor=[("active", t["menu_highlight"])])
        self.tree.update_idletasks()
        style.configure("Treeview", bordercolor=t["tree_frame_highlight"])
        style.configure("Treeview.Heading", bordercolor=t["tree_frame_highlight"])
        style.configure("Treeview", padding=0)
        style.configure("Treeview", focuscolor=t["tree_frame_highlight"])
        style.map("Treeview",
                  focuscolor=[("focus", t["tree_frame_highlight"])],
                  bordercolor=[("focus", t["tree_frame_highlight"])])
        style.configure("Treeview",
                        highlightthickness=0,
                        highlightbackground=t["tree_bg"],
                        highlightcolor=t["tree_bg"])
        style.map("Treeview",
                  highlightcolor=[("focus", t["tree_bg"])],
                  highlightbackground=[("focus", t["tree_bg"])])

        style.configure("Vertical.TScrollbar",
                        background=t["scrollbar_thumb"],
                        troughcolor=t["scrollbar_trough"],
                        bordercolor=t["scrollbar_border"],
                        arrowcolor=t["scrollbar_arrow"],
                        darkcolor=t["scrollbar_thumb_active"],
                        lightcolor=t["scrollbar_thumb"],
                        relief="flat",
                        arrowsize=14)
        style.map("Vertical.TScrollbar",
                  background=[("pressed", t["scrollbar_thumb_active"]),
                              ("active", t["scrollbar_thumb_hover"])],
                  arrowcolor=[("pressed", t["scrollbar_arrow_active"]),
                              ("active", t["scrollbar_arrow_hover"])],
                  bordercolor=[("pressed", t["scrollbar_thumb_active"]),
                               ("active", t["scrollbar_thumb_hover"])])

        style.configure("Horizontal.TScrollbar",
                        background=t["scrollbar_thumb"],
                        troughcolor=t["scrollbar_trough"],
                        bordercolor=t["scrollbar_border"],
                        arrowcolor=t["scrollbar_arrow"],
                        darkcolor=t["scrollbar_thumb_active"],
                        lightcolor=t["scrollbar_thumb"],
                        relief="flat",
                        arrowsize=14)
        style.map("Horizontal.TScrollbar",
                  background=[("pressed", t["scrollbar_thumb_active"]),
                              ("active", t["scrollbar_thumb_hover"])],
                  arrowcolor=[("pressed", t["scrollbar_arrow_active"]),
                              ("active", t["scrollbar_arrow_hover"])],
                  bordercolor=[("pressed", t["scrollbar_thumb_active"]),
                               ("active", t["scrollbar_thumb_hover"])])

        style.configure("TPanedwindow",
                        background=t["bg"],
                        bordercolor=t["bg"],
                        sashrelief="flat",
                        sashwidth=0,
                        sashpad=0)

        style.configure("TNotebook",
                        background=t["bg"],
                        borderwidth=0,
                        bordercolor=t["bg"])
        style.configure("TNotebook.Tab",
                        background=t["tree_bg"],
                        foreground=t["tree_fg"],
                        padding=[10, 5],
                        borderwidth=0,
                        bordercolor=t["tree_frame_highlight"])
        style.map("TNotebook.Tab",
                  background=[("selected", t["bg"])],
                  foreground=[("selected", t["menu_fg"])],
                  bordercolor=[("selected", t["menu_highlight"])])

        style.configure("Hotbar.Horizontal.TProgressbar", troughcolor=t["progress_trough"],
                        bordercolor=t["menu_highlight"],
                        background=t["progress_light"], lightcolor=t["progress_light"],
                        darkcolor=t["progress_dark"], thickness=18)

        self.console.configure(bg=t["console_bg"], fg=t["console_fg"],
                               selectbackground=t["select_bg"], selectforeground=t["select_fg"],
                               inactiveselectbackground=t["select_bg"])

        self._apply_button_semantics(t)
        self._update_open_dialogs_theme(t)

        self.on_build_select(None)

    def _get_theme_color(self, key):
        theme_name = self.settings.get("theme", "Стандартная")
        theme = self.THEMES.get(theme_name, self.THEMES["Стандартная"])
        return theme.get(key, "#4a4d50")

    def _apply_button_semantics(self, t):
        for btn_name, semantic in self.BUTTON_SEMANTICS.items():
            btn = getattr(self, btn_name)
            btn.configure(
                bg=t[f"btn_{semantic}_bg"],
                fg=t[f"btn_{semantic}_fg"],
                activebackground=t["menu_active_bg"],
                activeforeground=t["menu_active_fg"],
            )