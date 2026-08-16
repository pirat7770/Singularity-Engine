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
import pystray
from PIL import Image, ImageDraw

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

try:
    import pywinstyles
    PY_WINSTYLES = True
except ImportError:
    PY_WINSTYLES = False

from ui.mixins.system_mixin import SystemMixin
from ui.mixins.installer_mixin import InstallerMixin
from ui.mixins.build_mixin import BuildMixin
from ui.mixins.game_mixin import GameMixin
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


class SingularityEngineApp(tk.Tk, DialogsMixin, SystemMixin, InstallerMixin, BuildMixin, GameMixin):
    CONFIG_FILE = "config.json"
    CONFIG_VERSION = 56

    THEMES = THEMES
    BUSY_STATUSES = BUSY_STATUSES
    BUTTON_SEMANTICS = BUTTON_SEMANTICS
    STATUS_ICONS = STATUS_ICONS

    def __init__(self):
        super().__init__()
        self.withdraw()
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("SingularityEngine.1")
        except Exception:
            pass

        self.VERSION = "2.11"
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

        # --- Инициализация атрибутов, используемых в self.log() ---
        self._current_instance_id = None
        self._log_history = deque(maxlen=10000)
        self._log_pending = deque()
        self._log_timer = None
        # -----------------------------------------------------------

        self.TOOL_HASHES = {
            "python-3.14.7-amd64.exe": "9d9eb2709ef81bf5cd30db3c2096bdbc4ea10087c22e62f27d356b36f6ae9649",
            "python-3.14.7-arm64.exe": "9a3fe120cc81bc2cb099550f794d8356811f96a86c7f438519243c3485db928d",
            "Git-2.55.0.3-64-bit.exe": "af12577d0fdff74243a5988197aa49b957d5044edc17004f6ddf0768996f1dca",
            "Git-2.55.0.3-arm64.exe": "e3d7f5a2214f214f0a93cf0d8915dab236a0e91c7de6de70a7dbde9a61c794db",
            "dotnet-sdk-10.0.302-win-x64.exe": "b2618a69a4ae385eb03bde0de89468881318c6338b14e67574d691e145a7ce1c",
            "dotnet-sdk-10.0.302-win-arm64.exe": "bedf0d3ae61284252db8012dab3809879fb6d9721335414b68992d32a6da20bb",
        }

        if PY_WINSTYLES:
            try:
                pywinstyles.apply_style(self, "dark")
            except Exception as e:
                self.log(f"⚠ Не удалось применить тёмное оформление Windows: {e}", tag="warn")

        style = ttk.Style(self)
        style.theme_use("clam")
        self._configure_initial_styles(style)

        from utils.system import get_data_dir
        self.data_dir = get_data_dir()
        self.CONFIG_FILE = self.data_dir / "config.json"
        self.config_manager = ConfigManager(self.CONFIG_FILE)
        self.download_manager = DownloadManager()

        self.settings = self.config_manager.data.get("settings", self.config_manager.default_settings())
        self.repositories = self.config_manager.data.get("repositories", self.config_manager.default_repositories())
        self.log_filters = self.config_manager.data.get("log_filters",
                                                        {"client": True, "server": True, "manager": True})

        configured_builds_dir = self.settings.get("builds_dir", "")
        if configured_builds_dir:
            self.builds_dir = Path(configured_builds_dir)
        else:
            self.builds_dir = self.data_dir / "builds"
        self.builds_dir.mkdir(parents=True, exist_ok=True)

        self.cleanup_unused_git_cache()
        self.cleanup_old_download_cache()
        self._migrate_legacy_data()

        self.after(100, self.check_required_tools)

        self._running_subprocesses = []
        self._instances = {}
        self._instance_counter = {}
        self._active_operations = {}
        self._game_toggle_lock = False
        self._remove_repo_dialog = None
        self._nuget_disabled = False
        self._closing = False
        self._operation_procs = {}
        self._cancel_download = False
        self._download_cancel_event = threading.Event()
        self._download_start = 0
        self._last_download_time = 0
        self._last_download_bytes = 0
        self._last_download_log = -1
        self._operation_lock = False

        self.port_allocator = PortAllocator()
        self._refresh_system_path()

        self.settings_dialog = None
        self.settings_notebook = None
        self.settings_widgets = []
        self.settings_tabs = []

        self.create_widgets()
        self.after(0, self.refresh_builds_list)
        self.after(2000, self._auto_refresh_instances)
        self.after(3000, self.check_for_updates)

        self._init_console_tags()

        self.bind("<Button-1>", self._on_global_click)
        self.protocol("WM_DELETE_WINDOW", self._on_window_close)
        self.bind_all("<Control-c>", self.copy_selection)
        self.bind_all("<Control-C>", self.copy_selection)
        self.bind_all("<Control-v>", self._paste)
        self.bind_all("<Control-V>", self._paste)
        self.deiconify()

    # ================== Инициализация стилей ==================
    def _configure_initial_styles(self, style):
        style.configure("Treeview", borderwidth=0, relief="flat")
        style.configure(".", background="#2b2b2b", foreground="white",
                        fieldbackground="#1e1e1e", bordercolor="#008844",
                        lightcolor="#2a4a3a", darkcolor="#1a3a2a")
        style.configure("Treeview", background="#1e1e1e", fieldbackground="#1e1e1e",
                        foreground="white", rowheight=25)
        style.configure("Treeview.Heading", background="#2b2b2b", foreground="white",
                        font=("Arial", 9, "bold"), bordercolor="#008844", relief="flat")
        style.map("Treeview", background=[("selected", "#2d4a3a")])
        style.map("Treeview.Heading",
                  background=[("pressed", "#1a1a1a"), ("active", "#1e1e1e")],
                  foreground=[("pressed", "#00ff88"), ("active", "#00cc66")],
                  bordercolor=[("active", "#00cc66")])
        style.configure("TScrollbar", arrowcolor="#00cc66", arrowsize=12)
        style.map("TScrollbar",
                  arrowcolor=[("disabled", "#2a4a3a"), ("pressed", "#ffffff"), ("active", "#00ff88")])
        style.configure("Vertical.TScrollbar", background="#1a1a1a", troughcolor="#101010",
                        bordercolor="#008844", arrowcolor="#00cc66", darkcolor="#008844",
                        lightcolor="#008844", relief="flat")
        style.map("Vertical.TScrollbar",
                  background=[("pressed", "#006633"), ("active", "#008844")],
                  arrowcolor=[("pressed", "#00ff88"), ("active", "#00ff88")],
                  bordercolor=[("active", "#00cc66")])
        style.configure("Horizontal.TScrollbar", background="#1a1a1a", troughcolor="#101010",
                        bordercolor="#008844", arrowcolor="#00cc66", darkcolor="#008844",
                        lightcolor="#008844")
        style.map("Horizontal.TScrollbar",
                  background=[("pressed", "#006633"), ("active", "#008844")],
                  arrowcolor=[("pressed", "#00ff88"), ("active", "#00ff88")],
                  bordercolor=[("active", "#00cc66")])
        style.configure("Hotbar.Horizontal.TProgressbar", troughcolor="#333333", bordercolor="#555555",
                        background="#00cc66", lightcolor="#00cc66", darkcolor="#00994d", thickness=18)
        style.configure("TPanedwindow", background="#2b2b2b")
        style.configure("TPanedwindow", sashrelief="flat", sashwidth=4, sashpad=0)

    def _migrate_legacy_data(self):
        legacy_config = Path.cwd() / "config.json"
        if legacy_config.exists() and not self.CONFIG_FILE.exists():
            import shutil
            self.log("🔄 Перенос данных в новую папку...", tag="info")
            shutil.move(str(legacy_config), str(self.CONFIG_FILE))
            legacy_builds = Path.cwd() / "builds"
            if legacy_builds.exists() and not self.builds_dir.exists():
                shutil.move(str(legacy_builds), str(self.builds_dir))
            legacy_logs = Path.cwd() / "logs"
            if legacy_logs.exists():
                new_logs = self.data_dir / "logs"
                if not new_logs.exists():
                    shutil.move(str(legacy_logs), str(new_logs))

    def _init_console_tags(self):
        self.console.tag_config("error", foreground="#ff5555", font=("Consolas", 10, "bold"))
        self.console.tag_config("success", foreground="#00ff88", font=("Consolas", 10, "bold"))
        self.console.tag_config("warn", foreground="#ffaa00")
        self.console.tag_config("info", foreground="#32CD32")
        self.console.tag_config("bold", foreground="#ffffff", font=("Consolas", 10, "bold"))
        self.console.tag_config("operation", foreground="#66ccff")
        self.console.tag_config("done", foreground="#00ffaa", font=("Consolas", 10, "bold"))
        self.console.tag_config("cancel", foreground="#cc66cc")
        self.console.tag_config("server", foreground="#ffaa00")
        self.console.tag_config("server_warn", foreground="#ff6600")
        self.console.tag_config("server_error", foreground="#ff2200", font=("Consolas", 10, "bold"))
        self.console.tag_config("client", foreground="#00ccff")
        self.console.tag_config("client_warn", foreground="#00ffcc")
        self.console.tag_config("client_error", foreground="#ff00aa", font=("Consolas", 10, "bold"))

    # ================== Вспомогательные методы ==================
    def _paste(self, event=None):
        widget = self.focus_get()
        if isinstance(widget, (tk.Entry, tk.Text)):
            widget.event_generate("<<Paste>>")
            return "break"
        return None

    def _safe_progress_config(self, **kwargs):
        self.after(0, lambda: self.progress_bar.config(**kwargs))

    def _safe_progress_set(self, value):
        self.after(0, lambda: self.progress_var.set(value))

    def _safe_speed_set(self, text):
        self.after(0, lambda: self.lbl_speed.config(text=text))

    def _escape_powershell_arg(self, value):
        if not isinstance(value, str):
            value = str(value)
        value = value.replace('"', '\\"')
        value = value.replace('&', '`&')
        return f'"{value}"'

    def _on_window_close(self):
        if self.settings.get("minimize_to_tray", True):
            self._hide_to_tray()
        else:
            if self.confirm_exit_if_running():
                self._on_closing()

    def check_for_updates(self):
        from utils.updater import get_latest_release_asset, GITHUB_REPO
        latest, asset_url, asset_type = get_latest_release_asset()
        if latest is None:
            return
        latest_version = latest.lstrip("v")
        if latest_version == self.VERSION:
            return

        self.log(f"Доступна новая версия: {latest}", tag="done")
        self.notify_tray("Доступно обновление", f"Версия {latest} уже доступна.")

        if self.settings.get("auto_update", False):
            self.log("🔄 Автоматическое обновление включено. Скачиваю и устанавливаю...", tag="bold")
            if asset_url:
                self._download_and_run_update(asset_url, latest, asset_type)
            else:
                self.log("⚠ Не найден файл для обновления.", tag="warn")
            return

        if not asset_url:
            if messagebox.askyesno("Обновление",
                                   f"Найдена новая версия {latest}.\nОткрыть страницу релиза?"):
                import webbrowser
                webbrowser.open(f"https://github.com/{GITHUB_REPO}/releases/latest")
            return

        choice = messagebox.askyesnocancel(
            "Обновление",
            f"Найдена новая версия {latest}.\n\n"
            "Нажмите «Да», чтобы скачать и установить обновление.\n"
            "Нажмите «Нет», чтобы открыть страницу релиза.\n"
            "Нажмите «Отмена», чтобы отложить."
        )
        if choice is None:
            return
        if choice:
            self._download_and_run_update(asset_url, latest, asset_type)
        else:
            import webbrowser
            webbrowser.open(f"https://github.com/{GITHUB_REPO}/releases/latest")

    def _download_and_run_update(self, url, version, asset_type):
        self.log(f"⬇ Скачивание обновления {version}...", tag="bold")
        self.progress_bar.config(mode="determinate")
        self.progress_var.set(0)
        self.lbl_speed.config(text="Загрузка обновления...")

        def download_thread():
            try:
                self._download_cancel_event.clear()
                dest_name = f"SingularityEngine-{version}.{asset_type}"
                file_path = self.download_manager.download(
                    url, dest_name,
                    progress_callback=self._download_progress,
                    cancel_event=self._download_cancel_event
                )
                if not file_path:
                    raise Exception("Не удалось скачать обновление")

                launcher_exe = None
                if asset_type == "exe":
                    launcher_exe = file_path
                elif asset_type == "zip":
                    import zipfile, tempfile
                    extract_dir = tempfile.mkdtemp(prefix="singularity_update_")
                    with zipfile.ZipFile(file_path, 'r') as zf:
                        zf.extractall(extract_dir)
                    for root, dirs, files in os.walk(extract_dir):
                        for f in files:
                            if f.endswith(".exe"):
                                launcher_exe = os.path.join(root, f)
                                break
                        if launcher_exe:
                            break
                    if not launcher_exe:
                        raise Exception("В архиве не найден исполняемый файл")

                if not self._verify_installer_signature(str(launcher_exe)):
                    self.log("❌ Цифровая подпись обновления недействительна.", tag="error")
                    return

                self.log("✅ Обновление скачано. Запускаю установщик...", tag="success")
                subprocess.Popen([str(launcher_exe)])
                self.after(2000, self._on_closing)

            except Exception as e:
                self.log(f"❌ Ошибка при обновлении: {e}", tag="error")
            finally:
                self.after(0, self.progress_bar.stop)
                self.after(0, lambda: self.progress_bar.config(mode="determinate"))
                self.after(0, lambda: self.progress_var.set(0))
                self.after(0, lambda: self.lbl_speed.config(text="0.00 MiB/s"))

        threading.Thread(target=download_thread, daemon=True).start()

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
        from ui.custom_dialogs import install_custom_messageboxes
        install_custom_messageboxes(self)
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

    def open_builds_folder(self):
        if self.builds_dir.exists():
            sys_open_path(self.builds_dir)
        else:
            messagebox.showinfo("Папка не найдена", f"Папка сборок не существует:\n{self.builds_dir}")

    def _open_repo_menu(self):
        self._close_repo_menu()
        t = self.THEMES.get(self.settings.get("theme", "Стандартная"))

        menu = tk.Toplevel(self)
        menu.overrideredirect(True)
        menu.configure(bg=t["menu_bg"], bd=0, highlightthickness=0)

        commands = [
            ("Добавить", self.add_repository_dialog),
            ("Удалить", self.remove_repository_dialog),
            ("Корневая папка", self.open_builds_folder),
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
            return
        self._active_operations.pop(name, None)
        self._operation_lock = False
        self.progress_bar.stop()
        self.lbl_speed.config(text="0.00 MiB/s")
        self.progress_bar.config(mode="determinate")
        self.progress_var.set(0)
        self.after(0, self.refresh_builds_list)
        self.after(0, lambda: self._reenable_buttons())
        self.log(f"✔ Операция для '{name}' завершена", tag="done")

    def _check_disk_space(self):
        free = shutil.disk_usage(self.builds_dir).free
        if free < 1_000_000_000:
            self.log("⚠ На диске мало места. Сборка может завершиться ошибкой.", tag="warn")

    def stop_operation(self, name):
        self._download_cancel_event.set()
        self._cancel_download = True
        if name not in self._active_operations:
            return
        self.log(f"🛑 Отмена операции для '{name}'...", tag="cancel")

        for proc in self._operation_procs.get(name, []):
            if proc.poll() is None:
                try:
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                                   capture_output=True, text=True, timeout=10,
                                   startupinfo=self._hidden_startupinfo(),
                                   creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass

        if name in self.repositories:
            build_path = os.path.join(self.builds_dir, name)
            self.kill_processes_locking_folder(build_path)
            time.sleep(1)
            if not self._fast_remove_folder(build_path, name):
                time.sleep(2)
                self._fast_remove_folder(build_path, name)
        else:
            time.sleep(0.5)

        self._end_operation(name)
        self.log(f"✅ Операция для '{name}' отменена.", tag="success")

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

        if operation_running:
            if name != active_operation_name:
                if active_operation_name not in self.repositories:
                    self._set_buttons_state("disabled")
                    self.btn_run.config(text="Отменить", state="normal",
                                        command=lambda: self.stop_operation(active_operation_name))
                    self.btn_open_folder.config(state="disabled")
                    self.btn_open_upload.config(state="disabled")
                    return
                else:
                    self._set_buttons_state("disabled")
                    if status == "installed":
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
                "Обновление...", "Загрузка готовой сборки...", "Загрузка SDK...",
                "Авто-пересборка..."
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
        if name in self._active_operations:
            self.log(f"⚠ Операция '{operation_text}' уже выполняется для '{name}'.", tag="warn")
            return
        self._operation_lock = True
        self._set_operation(name, operation_text)
        if progress_mode == "indeterminate":
            self.progress_bar.config(mode="indeterminate")
            self.progress_bar.start()
        else:
            self.progress_bar.config(mode="determinate")
            self.progress_var.set(0)
        self.log(f"▶ {operation_text}", tag="operation")
        self.lbl_speed.config(text=operation_text)
        self._check_disk_space()

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
            try:
                subprocess.run(["taskkill", "/F", "/IM", "git.exe"], capture_output=True, timeout=5,
                               startupinfo=self._hidden_startupinfo(),
                               creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
                subprocess.run(["taskkill", "/F", "/IM", "dotnet.exe"], capture_output=True, timeout=5,
                               startupinfo=self._hidden_startupinfo(),
                               creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
                killed = True
                self.log("🛑 Процессы git/dotnet завершены через taskkill.", tag="warn")
            except Exception as e:
                self.log(f"⚠ Ошибка при завершении процессов: {e}", tag="warn")

        if killed:
            time.sleep(0.2)
        return killed

    def _fast_remove_folder(self, folder_path, name):
        if isinstance(folder_path, str):
            folder_path = Path(folder_path)
        self.kill_processes_locking_folder(str(folder_path))

        if sys.platform == "win32":
            try:
                subprocess.run(["cmd", "/c", "rmdir", "/s", "/q", str(folder_path)],
                               capture_output=True, timeout=10,
                               startupinfo=self._hidden_startupinfo(),
                               creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
                if not folder_path.exists():
                    self.log(f"✅ Папка {name} удалена через cmd.", tag="success")
                    return True
            except subprocess.TimeoutExpired:
                pass

        try:
            shutil.rmtree(str(folder_path), ignore_errors=True)
            if not folder_path.exists():
                self.log(f"✅ Папка {name} удалена через shutil.", tag="success")
                return True
        except Exception as e:
            self.log(f"⚠ Ошибка удаления через shutil: {e}", tag="warn")

        if sys.platform == "win32":
            ps_command = (
                f'Start-Process cmd -ArgumentList "/c", "rmdir", "/s", "/q", '
                f'"{str(folder_path)}" -Verb RunAs'
            )
            try:
                subprocess.Popen(["powershell", "-Command", ps_command],
                                 startupinfo=self._hidden_startupinfo(),
                                 creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
                self.after(1000, lambda: self._check_removed(str(folder_path), name))
            except Exception as e:
                self.log(f"❌ Ошибка повышения: {e}", tag="error")
        return False

    def _check_removed(self, folder_path, name):
        if not os.path.exists(folder_path):
            self.log(f"✅ Папка {name} удалена администратором.", tag="success")
        else:
            self.log(f"❌ Папка {name} всё ещё существует.", tag="error")

    def filter_git_line(self, line):
        percent_match = re.search(r'(\d+)%', line)
        if percent_match:
            percent = int(percent_match.group(1))
            self.after(0, self.progress_var.set, percent)

        speed_match = re.search(r'\|\s*([\d.]+\s*[a-zA-Z]+/s)', line)
        if speed_match:
            self.after(0, self.lbl_speed.config, {"text": speed_match.group(1)})
        return line

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

    def _update_open_dialogs_theme(self, t):
        if self.settings_dialog and self.settings_dialog.winfo_exists():
            self.settings_dialog.configure(bg=t["bg"])
        if self._repo_menu_window and self._repo_menu_window.winfo_exists():
            self._repo_menu_window.configure(bg=t["menu_bg"])

    # ================== Недостающие методы ==================
    def _download_progress(self, block_num, block_size, total_size):
        if total_size <= 0:
            self.after(0, self.progress_bar.config, {"mode": "indeterminate"})
            self.after(0, self.progress_bar.start)
            return

        percent = min(100, int(block_num * block_size * 100 / total_size))
        self.after(0, self.progress_var.set, percent)

        if percent % 10 == 0 and percent != self._last_download_log:
            self.log(f"⬇ Загрузка: {percent}%", tag="info")
            self._last_download_log = percent

        now = time.time()
        bytes_done = block_num * block_size
        dt = now - self._last_download_time
        if self._last_download_time == 0:
            self._last_download_time = now
            self._last_download_bytes = bytes_done
            return

        if dt > 0.5:
            speed = (bytes_done - self._last_download_bytes) / dt if dt > 0 else 0
            self._last_download_time = now
            self._last_download_bytes = bytes_done

            if speed >= 1024 * 1024:
                speed_text = f"{speed / (1024 * 1024):.2f} MiB/s"
            elif speed >= 1024:
                speed_text = f"{speed / 1024:.2f} KiB/s"
            else:
                speed_text = f"{speed:.0f} B/s"

            eta_text = ""
            if speed > 0:
                remaining_bytes = total_size - bytes_done
                remaining_sec = remaining_bytes / speed
                if remaining_sec > 60:
                    mins = int(remaining_sec // 60)
                    secs = int(remaining_sec % 60)
                    eta_text = f" · осталось {mins:02d}:{secs:02d}"
                else:
                    eta_text = f" · осталось {int(remaining_sec)} сек"

            self.after(0, self.lbl_speed.config, {"text": speed_text + eta_text})

    def _reenable_buttons(self):
        self._set_buttons_state("normal")
        self.tree.config(selectmode="browse")
        self.on_build_select(None)

    def _install_success(self, name):
        self.progress_bar.stop()
        self.progress_bar.config(mode="determinate")
        self.progress_var.set(100)
        self.lbl_speed.config(text="Готово")
        self.log("=== Установка успешно завершена ===", tag="done")
        self.notify_tray("Установка завершена", f"Сборка '{name}' успешно установлена.")
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
            except Exception as e:
                self.log(f"⚠ Ошибка при завершении процесса: {e}", tag="warn")
        for instance_id, inst in self._instances.items():
            for p in (inst["srv"], inst["cli"]):
                if p and p.poll() is None:
                    try:
                        p.terminate()
                        p.wait(timeout=2)
                    except:
                        try:
                            p.kill()
                        except Exception as e:
                            self.log(f"⚠ Ошибка при завершении процесса: {e}", tag="warn")
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

    def _hide_to_tray(self):
        self.withdraw()
        if self.tray_icon is None:
            self._create_tray_icon()

    def _restore_from_tray(self):
        self.after(0, self._show_window)

    def _show_window(self):
        self.deiconify()
        self.state('normal')
        self.lift()
        self.focus_force()

    def _exit_from_tray(self):
        if self.tray_icon:
            self.tray_icon.stop()
        self.after(0, lambda: self._on_closing() if self.confirm_exit_if_running() else None)

    def _create_tray_icon(self):
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

    def show_notification(self, title, message):
        messagebox.showinfo(title, message)

    def refresh_builds_list(self):
        selected = self.tree.selection()
        selected_name = selected[0] if selected else None
        self.tree.delete(*self.tree.get_children())

        def status_sort_key(status):
            """Возвращает числовой приоритет статуса (меньше = выше)."""
            if status == "installed":
                return 0
            if status in self.BUSY_STATUSES:
                return 1
            if status == "partial_build":
                return 2
            if status == "clone_incomplete":
                return 3
            if status == "missing":
                return 4
            return 5  # unknown

        def sort_key(name):
            repo_data = self.repositories[name]
            is_fav = repo_data.get("favorite", False)
            status = self.get_build_status(name)
            return (0 if is_fav else 1, 0, name.lower())

        sorted_repos = sorted(self.repositories.items(), key=lambda item: sort_key(item[0]))

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