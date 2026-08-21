# ui/dialogs.py
import tkinter as tk
from tkinter import ttk, messagebox
import os
import shutil
import re
import time
from pathlib import Path
import sys
import threading
import subprocess
from ui.widgets import ToolTip, show_notification
from utils.system import open_path as sys_open_path

class DialogsMixin:
    """Миксин для всех диалоговых окон и утилит корзины."""

    # ================== Уведомления ==================
    def show_notification(self, title, message, duration=5000):
        """Обёртка для вызова внешней функции show_notification."""
        theme = self.THEMES.get(self.settings.get("theme", "Стандартная"), self.THEMES["Стандартная"])
        show_notification(self, title, message, theme, duration)

    # ================== Вспомогательные методы для полей ввода ==================

    def _bind_paste(self, widget):
        """Привязывает корректную вставку, работающую на любой раскладке."""

        def _paste_once(event=None):
            try:
                text = widget.clipboard_get()
                widget.insert("insert", text)
                return "break"
            except tk.TclError:
                return

        # Перехват по физической клавише V (keycode 86) с Ctrl
        def _on_key_press(event):
            if event.state & 0x4 and event.keycode == 86:
                return _paste_once(event)
            return None

        widget.bind("<KeyPress>", _on_key_press)  # сработает на любой раскладке
        widget.bind("<Control-v>", _paste_once)  # английская раскладка (дополнительно)
        widget.bind("<Control-V>", _paste_once)
        widget.bind("<Shift-Insert>", _paste_once)  # альтернативный способ

        # Контекстное меню по правой кнопке мыши
        def _show_menu(event):
            menu = tk.Menu(widget, tearoff=0)
            menu.add_command(label="Вставить", command=_paste_once)
            menu.tk_popup(event.x_root, event.y_root)

        widget.bind("<Button-3>", _show_menu)

    def _normalize_repo_url(self, url: str) -> str:
        """Очищает и проверяет URL репозитория, удаляя случайные дубли."""
        url = url.strip()
        if not url:
            return ""
        # Удаляем повторяющиеся подстроки, если URL случайно задвоился/заутроился
        for i in range(1, len(url)):
            if url[:i] == url[i:i+i]:
                url = url[:i]
                break
        # Убираем завершающие слэши
        url = url.rstrip('/')
        # Проверяем, что это похоже на git URL
        if not re.match(r'^(https?|git)://.+\..+', url):
            return ""
        return url

    # ================== Настройки ==================

    def _browse_builds_dir(self, var):
        from tkinter import filedialog
        chosen = filedialog.askdirectory(initialdir=var.get() or str(self.builds_dir))
        if chosen:
            var.set(chosen)

    def open_settings_dialog(self):
        original_theme = self.settings.get("theme", "Стандартная")
        t = self.THEMES.get(original_theme)

        if self.settings_dialog is not None and self.settings_dialog.winfo_exists():
            self.settings_dialog.lift()
            return

        dialog = tk.Toplevel(self)
        self.settings_dialog = dialog
        dialog.title("Настройки")
        dialog.geometry("680x720")
        dialog.configure(bg=t["bg"])
        dialog.resizable(False, False)
        dialog.grab_set()
        dialog.protocol("WM_DELETE_WINDOW", lambda: self._close_settings_dialog(dialog))

        notebook = ttk.Notebook(dialog)
        self.settings_notebook = notebook
        style = ttk.Style()
        style.configure("TNotebook", background=t["bg"], borderwidth=0)
        style.configure("TNotebook.Tab", background=t["tree_bg"], foreground=t["tree_fg"],
                        padding=[12, 6], bordercolor=t["tree_frame_highlight"])
        style.map("TNotebook.Tab",
                  background=[("selected", t["bg"])],
                  foreground=[("selected", t["menu_fg"])],
                  bordercolor=[("selected", t["menu_highlight"])])
        notebook.pack(fill="both", expand=True, padx=5, pady=5)

        # ===== Стилизация Combobox с цветной рамкой =====
        style.configure("Console.TCombobox",
                        fieldbackground=t["tree_bg"],
                        background=t["tree_bg"],
                        foreground=t["tree_fg"],
                        arrowcolor=t["menu_fg"],
                        bordercolor=t["tree_frame_highlight"],      # рамка без фокуса
                        lightcolor=t["tree_bg"],
                        darkcolor=t["tree_bg"],
                        selectbackground=t["tree_sel_bg"],
                        selectforeground=t["tree_fg"],
                        focuscolor=t["menu_highlight"],             # цвет рамки фокуса (пунктир)
                        highlightthickness=1,                       # толщина рамки
                        highlightbackground=t["tree_frame_highlight"],
                        highlightcolor=t["menu_highlight"],
                        borderwidth=1,
                        relief="solid")
        style.map("Console.TCombobox",
                  fieldbackground=[("readonly", t["tree_bg"]),
                                   ("focus", t["tree_bg"])],
                  foreground=[("readonly", t["tree_fg"]),
                              ("focus", t["tree_fg"])],
                  background=[("readonly", t["tree_bg"])],
                  selectbackground=[("readonly", t["tree_sel_bg"])],
                  selectforeground=[("readonly", t["tree_fg"])],
                  bordercolor=[("focus", t["menu_highlight"])],     # при фокусе рамка становится яркой
                  highlightcolor=[("focus", t["menu_highlight"])],
                  focuscolor=[("focus", t["menu_highlight"])])

        # Стиль для выпадающего списка (popdown listbox)
        style.configure("Console.TCombobox.Listbox",
                        background=t["tree_bg"],
                        foreground=t["tree_fg"],
                        selectbackground=t["tree_sel_bg"],
                        selectforeground=t["tree_fg"],
                        borderwidth=0,
                        relief="flat",
                        highlightthickness=0)

        # Дополнительные настройки для listbox (на случай, если стиль не применится)
        self.option_add("*TCombobox*Listbox*Background", t["tree_bg"])
        self.option_add("*TCombobox*Listbox*Foreground", t["tree_fg"])
        self.option_add("*TCombobox*Listbox*selectBackground", t["tree_sel_bg"])
        self.option_add("*TCombobox*Listbox*selectForeground", t["tree_fg"])

        self.settings_widgets.clear()
        self.settings_tabs.clear()

        # ===== Переменные =====
        keep_finished_var = tk.BooleanVar(value=self.settings.get("keep_finished_instances", True))
        max_inst_var = tk.IntVar(value=self.settings.get("max_instances", 5))
        auto_del_var = tk.BooleanVar(value=self.settings.get("auto_delete_failed", False))
        confirm_clean_var = tk.BooleanVar(value=self.settings.get("confirm_clean_rebuild", False))
        shallow_var = tk.BooleanVar(value=self.settings.get("shallow_clone", False))
        parallel_var = tk.BooleanVar(value=self.settings.get("parallel_build", False))
        pre_restore_var = tk.BooleanVar(value=self.settings.get("pre_restore", False))
        strict_sdk_var = tk.BooleanVar(value=self.settings.get("strict_sdk_major", True))
        auto_deps_var = tk.BooleanVar(value=self.settings.get("auto_install_deps", False))
        confirm_destructive_var = tk.BooleanVar(value=self.settings.get("confirm_destructive", True))
        minimize_to_tray_var = tk.BooleanVar(value=self.settings.get("minimize_to_tray", True))
        enable_git_cache_var = tk.BooleanVar(value=self.settings.get("enable_git_cache", True))
        builds_dir_var = tk.StringVar(value=self.settings.get("builds_dir", ""))
        verify_signature_var = tk.BooleanVar(value=self.settings.get("verify_installer_signature", True))
        current_theme = tk.StringVar(value=original_theme)

        # Настройки консоли
        console_font_family_var = tk.StringVar(value=self.settings.get("console_font_family", "Consolas"))
        console_font_size_var = tk.IntVar(value=self.settings.get("console_font_size", 10))
        console_line_spacing_var = tk.IntVar(value=self.settings.get("console_line_spacing", 2))
        console_wrap_var = tk.StringVar(value=self.settings.get("console_wrap", "word"))

        def add_section(parent, title):
            """Создаёт контейнер с заголовком секции."""
            frame = tk.Frame(parent, bg=t["bg"])
            frame.pack(fill="x", padx=15, pady=8)
            lbl = tk.Label(frame, text=title, bg=t["bg"], fg=t["menu_fg"],
                           font=("Arial", 10, "bold"))
            lbl.pack(anchor="w", pady=(0, 4))
            self.settings_widgets.extend([frame, lbl])
            return frame

        # ===== Вкладка "Общие" =====
        tab_general = tk.Frame(notebook, bg=t["bg"])
        notebook.add(tab_general, text="Общие")
        self.settings_tabs.append(tab_general)

        section = add_section(tab_general, "Поведение окна")
        cb = tk.Checkbutton(section, text="Сворачивать в трей при закрытии",
                            variable=minimize_to_tray_var, bg=t["bg"], fg=t["fg"],
                            selectcolor=t["bg"], activebackground=t["bg"],
                            activeforeground=t["menu_fg"])
        cb.pack(anchor="w", padx=10)
        self.settings_widgets.append(cb)

        section = add_section(tab_general, "Экземпляры")
        row = tk.Frame(section, bg=t["bg"])
        row.pack(anchor="w", padx=10)
        cb = tk.Checkbutton(row, text="Сохранять завершённые экземпляры",
                            variable=keep_finished_var, bg=t["bg"], fg=t["fg"],
                            selectcolor=t["bg"], activebackground=t["bg"],
                            activeforeground=t["menu_fg"])
        cb.pack(side="left")
        self.settings_widgets.extend([row, cb])

        row2 = tk.Frame(section, bg=t["bg"])
        row2.pack(anchor="w", padx=10, pady=(8, 0))
        tk.Label(row2, text="Максимум экземпляров одной сборки:",
                 bg=t["bg"], fg=t["fg"]).pack(side="left")
        spin = tk.Spinbox(row2, from_=1, to=10, width=4, textvariable=max_inst_var,
                          bg=t["tree_bg"], fg=t["tree_fg"], buttonbackground=t["tree_bg"],
                          insertbackground=t["tree_fg"])
        spin.pack(side="left", padx=6)
        self.settings_widgets.extend([row2, spin])

        section = add_section(tab_general, "Безопасность")
        cb = tk.Checkbutton(section, text="Подтверждать удаление и переустановку",
                            variable=confirm_destructive_var, bg=t["bg"], fg=t["fg"],
                            selectcolor=t["bg"], activebackground=t["bg"],
                            activeforeground=t["menu_fg"])
        cb.pack(anchor="w", padx=10)
        self.settings_widgets.append(cb)

        cb = tk.Checkbutton(section, text="Требовать действительную цифровую подпись установщиков",
                            variable=verify_signature_var, bg=t["bg"], fg=t["fg"],
                            selectcolor=t["bg"], activebackground=t["bg"],
                            activeforeground=t["menu_fg"])
        cb.pack(anchor="w", padx=10)
        self.settings_widgets.append(cb)

        # ===== Вкладка "Сборка" =====
        tab_build = tk.Frame(notebook, bg=t["bg"])
        notebook.add(tab_build, text="Сборка")
        self.settings_tabs.append(tab_build)

        section = add_section(tab_build, "Git")
        for var, text in [
            (shallow_var, "Мелкое клонирование (shallow clone)"),
            (enable_git_cache_var, "Сохранять git-кэш при удалении")
        ]:
            cb = tk.Checkbutton(section, text=text, variable=var, bg=t["bg"], fg=t["fg"],
                                selectcolor=t["bg"], activebackground=t["bg"],
                                activeforeground=t["menu_fg"])
            cb.pack(anchor="w", padx=10)
            self.settings_widgets.append(cb)

        section = add_section(tab_build, "Компиляция")
        for var, text in [
            (parallel_var, "Параллельная сборка (dotnet build -m)"),
            (pre_restore_var, "Предварительное восстановление пакетов"),
            (strict_sdk_var, "Строго соблюдать major-версию SDK")
        ]:
            cb = tk.Checkbutton(section, text=text, variable=var, bg=t["bg"], fg=t["fg"],
                                selectcolor=t["bg"], activebackground=t["bg"],
                                activeforeground=t["menu_fg"])
            cb.pack(anchor="w", padx=10)
            self.settings_widgets.append(cb)

        section = add_section(tab_build, "Автоматизация")
        auto_update_var = tk.BooleanVar(value=self.settings.get("auto_update", False))
        check_updates_var = tk.BooleanVar(value=self.settings.get("check_updates", True))
        cb = tk.Checkbutton(section, text="Проверять обновления при запуске",
                            variable=check_updates_var, bg=t["bg"], fg=t["fg"],
                            selectcolor=t["bg"], activebackground=t["bg"],
                            activeforeground=t["menu_fg"])
        cb.pack(anchor="w", padx=10)
        self.settings_widgets.append(cb)
        cb = tk.Checkbutton(section, text="Автоматически скачивать и устанавливать обновления",
                            variable=auto_update_var, bg=t["bg"], fg=t["fg"],
                            selectcolor=t["bg"], activebackground=t["bg"],
                            activeforeground=t["menu_fg"])
        cb.pack(anchor="w", padx=10)
        self.settings_widgets.append(cb)
        cb = tk.Checkbutton(section, text="Автоматически устанавливать недостающие зависимости",
                            variable=auto_deps_var, bg=t["bg"], fg=t["fg"],
                            selectcolor=t["bg"], activebackground=t["bg"],
                            activeforeground=t["menu_fg"])
        cb.pack(anchor="w", padx=10)
        self.settings_widgets.append(cb)
        cb = tk.Checkbutton(section, text="Автоматически удалять неудавшиеся сборки",
                            variable=auto_del_var, bg=t["bg"], fg=t["fg"],
                            selectcolor=t["bg"], activebackground=t["bg"],
                            activeforeground=t["menu_fg"])
        cb.pack(anchor="w", padx=10)
        self.settings_widgets.append(cb)

        section = add_section(tab_build, "Папка сборок")
        row = tk.Frame(section, bg=t["bg"])
        row.pack(fill="x", padx=10)
        entry = tk.Entry(row, textvariable=builds_dir_var, bg=t["tree_bg"], fg=t["tree_fg"],
                         insertbackground=t["tree_fg"])
        entry.pack(side="left", fill="x", expand=True)
        self._bind_paste(entry)
        btn = tk.Button(row, text="Обзор...", bg=t["btn_default_bg"], fg=t["btn_default_fg"],
                        activebackground=t["menu_active_bg"], activeforeground=t["menu_active_fg"],
                        command=lambda: self._browse_builds_dir(builds_dir_var))
        btn.pack(side="left", padx=5)
        self.settings_widgets.extend([row, entry, btn])

        # ===== Вкладка "Оформление" =====
        tab_theme = tk.Frame(notebook, bg=t["bg"])
        notebook.add(tab_theme, text="Оформление")
        self.settings_tabs.append(tab_theme)

        section = add_section(tab_theme, "Тема оформления")
        theme_radios = []
        for name in self.THEMES:
            rb = tk.Radiobutton(section, text=name, variable=current_theme, value=name,
                                bg=t["bg"], fg=t["fg"], selectcolor=t["bg"],
                                activebackground=t["bg"], activeforeground=t["menu_fg"],
                                command=lambda n=name: self.apply_theme(n))
            rb.pack(anchor="w", padx=10, pady=3)
            theme_radios.append(rb)
        self.settings_widgets.extend(theme_radios)

        # ===== Вкладка "Консоль" =====
        tab_console = tk.Frame(notebook, bg=t["bg"])
        notebook.add(tab_console, text="Консоль")
        self.settings_tabs.append(tab_console)

        section = add_section(tab_console, "Шрифт")
        row = tk.Frame(section, bg=t["bg"])
        row.pack(fill="x", padx=10, pady=2)
        tk.Label(row, text="Семейство:", bg=t["bg"], fg=t["fg"]).pack(side="left")
        font_combo = ttk.Combobox(row, textvariable=console_font_family_var,
                                  values=["Consolas", "Courier New", "Cascadia Code", "Arial", "Times New Roman"],
                                  style="Console.TCombobox")
        font_combo.configure(takefocus=False)
        font_combo.pack(side="left", padx=5)
        self.settings_widgets.extend([row, font_combo])

        row = tk.Frame(section, bg=t["bg"])
        row.pack(fill="x", padx=10, pady=2)
        tk.Label(row, text="Размер:", bg=t["bg"], fg=t["fg"]).pack(side="left")
        spin_size = tk.Spinbox(row, from_=8, to=16, textvariable=console_font_size_var, width=4,
                               bg=t["tree_bg"], fg=t["tree_fg"],
                               buttonbackground=t["tree_bg"], insertbackground=t["tree_fg"])
        spin_size.pack(side="left", padx=5)
        self.settings_widgets.extend([row, spin_size])

        row = tk.Frame(section, bg=t["bg"])
        row.pack(fill="x", padx=10, pady=2)
        tk.Label(row, text="Интервал между строками:", bg=t["bg"], fg=t["fg"]).pack(side="left")
        spin_spacing = tk.Spinbox(row, from_=0, to=10, textvariable=console_line_spacing_var, width=4,
                                  bg=t["tree_bg"], fg=t["tree_fg"],
                                  buttonbackground=t["tree_bg"], insertbackground=t["tree_fg"])
        spin_spacing.pack(side="left", padx=5)
        self.settings_widgets.extend([row, spin_spacing])

        # ===== Вкладка "Инструменты" =====
        tab_tools = tk.Frame(notebook, bg=t["bg"])
        notebook.add(tab_tools, text="Инструменты")
        self.settings_tabs.append(tab_tools)

        section = add_section(tab_tools, "Необходимые компоненты")

        def build_tool_row(parent, label_text, check_func, install_cmd):
            row = tk.Frame(parent, bg=t["bg"])
            row.pack(fill="x", padx=10, pady=6)

            lbl = tk.Label(row, text=f"{label_text}: проверка...", bg=t["bg"], fg=t["fg"])
            lbl.pack(side="left")

            btn = tk.Button(row, text="Установить/Переустановить",
                            bg=t["btn_accent_bg"], fg=t["btn_accent_fg"],
                            activebackground=t["menu_active_bg"], activeforeground=t["menu_active_fg"],
                            command=install_cmd)
            btn.pack(side="right")

            self.settings_widgets.extend([row, lbl, btn])

            def check_in_background():
                try:
                    ok = check_func()
                except Exception:
                    ok = False

                def update_label(ok=ok, label_text=label_text):
                    if lbl.winfo_exists():
                        status = "✅ Установлен" if ok else "❌ Не установлен"
                        fg = t["btn_accent_fg"] if ok else t["btn_danger_fg"]
                        lbl.config(text=f"{label_text}: {status}", fg=fg)

                self.after(0, update_label)

            threading.Thread(target=check_in_background, daemon=True).start()
            return row, lbl, btn

        def check_dotnet():
            if not self._is_tool_installed("dotnet"):
                return False
            installed = self._get_installed_sdks()
            return any(v.startswith("9.") or v.startswith("10.") for v in installed)

        build_tool_row(section, "Git",
                       lambda: self._is_tool_installed("git"),
                       lambda: self._download_and_run_installer("Git", self._get_git_url()))
        build_tool_row(section, "Python",
                       lambda: self._is_python_installed(),
                       lambda: self._download_and_run_installer("Python", self._get_python_installer_url()))
        build_tool_row(section, ".NET SDK 9/10", check_dotnet,
                       lambda: self._download_and_install_sdk("10.0.302", None, None))

        btn_logs = tk.Button(section, text="Открыть папку с логами",
                             bg=t["btn_default_bg"], fg=t["btn_default_fg"],
                             activebackground=t["menu_active_bg"], activeforeground=t["menu_active_fg"],
                             command=self.open_logs_folder)
        btn_logs.pack(pady=10)
        self.settings_widgets.append(btn_logs)

        # ===== Вкладка "Очистка" =====
        tab_cleanup = tk.Frame(notebook, bg=t["bg"])
        notebook.add(tab_cleanup, text="Очистка")
        self.settings_tabs.append(tab_cleanup)

        section = add_section(tab_cleanup, "Кэш и временные файлы")
        btn_clear_cache = tk.Button(section, text="Очистить весь кэш",
                                    bg=t["btn_danger_bg"], fg=t["btn_danger_fg"],
                                    activebackground=t["menu_active_bg"], activeforeground=t["menu_active_fg"],
                                    command=self.clear_cache)
        btn_clear_cache.pack(fill="x", padx=10, pady=5)
        self.settings_widgets.append(btn_clear_cache)
        btn_clear_dl = tk.Button(section, text="Очистить кэш загрузок",
                                 bg=t["btn_default_bg"], fg=t["btn_default_fg"],
                                 activebackground=t["menu_active_bg"], activeforeground=t["menu_active_fg"],
                                 command=self.clear_download_cache)
        btn_clear_dl.pack(fill="x", padx=10, pady=5)
        self.settings_widgets.append(btn_clear_dl)

        # ===== Кнопки сохранения =====
        btn_frame = tk.Frame(dialog, bg=t["bg"])
        btn_frame.pack(pady=12)

        def save():
            # Сохраняем все настройки
            self.settings["auto_delete_failed"] = auto_del_var.get()
            self.settings["confirm_clean_rebuild"] = confirm_clean_var.get()
            self.settings["shallow_clone"] = shallow_var.get()
            self.settings["parallel_build"] = parallel_var.get()
            self.settings["pre_restore"] = pre_restore_var.get()
            self.settings["check_updates"] = check_updates_var.get()
            self.settings["strict_sdk_major"] = strict_sdk_var.get()
            self.settings["auto_install_deps"] = auto_deps_var.get()
            self.settings["confirm_destructive"] = confirm_destructive_var.get()
            self.settings["minimize_to_tray"] = minimize_to_tray_var.get()
            self.settings["enable_git_cache"] = enable_git_cache_var.get()
            self.settings["auto_update"] = auto_update_var.get()
            self.settings["keep_finished_instances"] = keep_finished_var.get()
            self.settings["max_instances"] = max_inst_var.get()
            self.settings["builds_dir"] = builds_dir_var.get().strip()
            self.settings["verify_installer_signature"] = verify_signature_var.get()
            self.settings["theme"] = current_theme.get()

            # Настройки консоли
            self.settings["console_font_family"] = console_font_family_var.get()
            self.settings["console_font_size"] = console_font_size_var.get()
            self.settings["console_line_spacing"] = console_line_spacing_var.get()
            self.settings["console_wrap"] = console_wrap_var.get()

            self.save_settings()
            self.log("Настройки сохранены.", tag="info")

            # Применяем настройки консоли немедленно
            self._init_console_tags()
            self._rebuild_console()  # если метод существует, иначе можно не вызывать

            self._close_settings_dialog(dialog)

        def reset():
            auto_del_var.set(False)
            confirm_clean_var.set(False)
            shallow_var.set(False)
            auto_update_var.set(False)
            parallel_var.set(False)
            pre_restore_var.set(False)
            strict_sdk_var.set(True)
            check_updates_var.set(True)
            auto_deps_var.set(False)
            confirm_destructive_var.set(True)
            keep_finished_var.set(True)
            max_inst_var.set(5)
            builds_dir_var.set("")
            verify_signature_var.set(True)
            current_theme.set("Стандартная")
            self.apply_theme("Стандартная")

            # Сбрасываем настройки консоли
            console_font_family_var.set("Consolas")
            console_font_size_var.set(10)
            console_line_spacing_var.set(2)
            console_wrap_var.set("word")

        def cancel():
            self._close_settings_dialog(dialog)

        save_btn = tk.Button(btn_frame, text="Сохранить", bg=t["btn_accent_bg"], fg=t["btn_accent_fg"],
                             activebackground=t["menu_active_bg"], activeforeground=t["menu_active_fg"],
                             command=save)
        save_btn.pack(side="left", padx=10)
        reset_btn = tk.Button(btn_frame, text="По умолчанию", bg=t["btn_default_bg"], fg=t["btn_default_fg"],
                              activebackground=t["menu_active_bg"], activeforeground=t["menu_active_fg"],
                              command=reset)
        reset_btn.pack(side="left", padx=10)
        cancel_btn = tk.Button(btn_frame, text="Отмена", bg=t["btn_default_bg"], fg=t["btn_default_fg"],
                               activebackground=t["menu_active_bg"], activeforeground=t["menu_active_fg"],
                               command=cancel)
        cancel_btn.pack(side="right", padx=10)

        self.settings_widgets.extend([save_btn, reset_btn, cancel_btn])

    # ================== Репозитории ==================

    def open_cache_folder(self):
        """Открывает папку кэша загрузок (установщики)."""
        cache_dir = self.download_manager.cache_dir
        cache_dir.mkdir(parents=True, exist_ok=True)
        sys_open_path(cache_dir)

    def clear_cache(self):
        self.clear_download_cache()

        git_cache_dir = Path(self.builds_dir) / ".git_cache"
        if not git_cache_dir.exists():
            self.log("ℹ Git-кэш уже пуст.", tag="info")
            return

        def worker():
            self.kill_processes_locking_folder(str(git_cache_dir))
            time.sleep(0.5)

            try:
                shutil.rmtree(git_cache_dir, ignore_errors=True)
                if not git_cache_dir.exists():
                    self.after(0, lambda: self.log("🧹 Git-кэш очищен.", tag="success"))
                    return
            except Exception:
                pass

            if sys.platform == "win32":
                try:
                    subprocess.run(
                        ["cmd", "/c", "rmdir", "/s", "/q", str(git_cache_dir)],
                        capture_output=True, timeout=10,
                        startupinfo=self._hidden_startupinfo(),
                        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
                    )
                    if not git_cache_dir.exists():
                        self.after(0, lambda: self.log("🧹 Git-кэш очищен через cmd.", tag="success"))
                        return
                except Exception:
                    pass

            self.after(0, lambda: self.log(
                "❌ Не удалось очистить git-кэш: файлы заняты другим процессом.", tag="error"
            ))

        threading.Thread(target=worker, daemon=True).start()

    def clear_download_cache(self):
        cache_dir = self.download_manager.cache_dir
        if not cache_dir.exists():
            messagebox.showinfo("Кэш", "Кэш загрузок пуст.")
            return
        if not messagebox.askyesno("Очистить кэш загрузок", "Удалить все кэшированные установщики?"):
            return

        def worker():
            try:
                shutil.rmtree(cache_dir)
                cache_dir.mkdir(parents=True, exist_ok=True)
                self.after(0, lambda: self.log("🧹 Кэш установщиков очищен.", tag="success"))
            except Exception as e:
                self.after(0, lambda e=e: self.log(
                    f"❌ Не удалось очистить кэш установщиков: {e}", tag="error"
                ))

        threading.Thread(target=worker, daemon=True).start()

    def add_repository_dialog(self):
        t = self.THEMES.get(self.settings.get("theme", "Стандартная"))
        dialog = tk.Toplevel(self)
        dialog.title("Добавить репозиторий")
        dialog.geometry("400x280")
        dialog.configure(bg=t["bg"])
        dialog.resizable(False, False)
        dialog.grab_set()

        tk.Label(dialog, text="Название сборки:", bg=t["bg"], fg=t["fg"]).pack(pady=(10, 0))
        name_var = tk.StringVar()
        name_entry = tk.Entry(dialog, textvariable=name_var, bg=t["tree_bg"], fg=t["tree_fg"],
                              insertbackground=t["tree_fg"])
        name_entry.pack(pady=5, padx=20, fill="x")
        self._bind_paste(name_entry)  # <-- корректная вставка

        tk.Label(dialog, text="Git URL:", bg=t["bg"], fg=t["fg"]).pack(pady=(5, 0))
        url_var = tk.StringVar()
        url_entry = tk.Entry(dialog, textvariable=url_var, bg=t["tree_bg"], fg=t["tree_fg"],
                             insertbackground=t["tree_fg"])
        url_entry.pack(pady=5, padx=20, fill="x")
        self._bind_paste(url_entry)  # <-- корректная вставка

        tk.Label(dialog, text="Режим сборки:", bg=t["bg"], fg=t["fg"]).pack(pady=(5, 0))
        mode_var = tk.StringVar(value="Debug")
        mode_frame = tk.Frame(dialog, bg=t["bg"])
        mode_frame.pack(pady=5)
        tk.Radiobutton(mode_frame, text="Debug", variable=mode_var, value="Debug",
                       bg=t["bg"], fg=t["fg"], selectcolor=t["bg"],
                       activebackground=t["bg"], activeforeground=t["tree_fg"]).pack(side="left", padx=10)
        tk.Radiobutton(mode_frame, text="Release", variable=mode_var, value="Release",
                       bg=t["bg"], fg=t["fg"], selectcolor=t["bg"],
                       activebackground=t["bg"], activeforeground=t["tree_fg"]).pack(side="left", padx=10)

        tk.Label(dialog, text="URL готовой сборки (опционально):", bg=t["bg"], fg=t["fg"]).pack(pady=(5, 0))
        prebuilt_var = tk.StringVar()
        prebuilt_entry = tk.Entry(dialog, textvariable=prebuilt_var, bg=t["tree_bg"], fg=t["tree_fg"],
                                  insertbackground=t["tree_fg"])
        prebuilt_entry.pack(pady=5, padx=20, fill="x")
        self._bind_paste(prebuilt_entry)  # <-- корректная вставка

        def add():
            name = name_var.get().strip()
            url = self._normalize_repo_url(url_var.get())
            if not name or not re.match(r'^[\w\- ]+$', name) or name in self.repositories:
                messagebox.showerror("Ошибка", "Проверьте правильность названия.", parent=dialog)
                return
            if not url:
                messagebox.showerror("Ошибка", "Введите корректный URL репозитория.", parent=dialog)
                return

            repo_data = {"url": url, "mode": mode_var.get(), "favorite": False}
            if prebuilt_var.get().strip():
                prebuilt_url = self._normalize_repo_url(prebuilt_var.get())
                if not prebuilt_url:
                    messagebox.showerror("Ошибка", "Некорректный URL готовой сборки.", parent=dialog)
                    return
                repo_data["prebuilt_url"] = prebuilt_url
            self.repositories[name] = repo_data
            self.save_config()
            self.after_idle(self.refresh_builds_list)
            dialog.destroy()

        btn_frame = tk.Frame(dialog, bg=t["bg"])
        btn_frame.pack(pady=15)
        tk.Button(btn_frame, text="Добавить", bg=t["btn_accent_bg"], fg=t["btn_accent_fg"],
                  activebackground=t["menu_active_bg"], activeforeground=t["menu_active_fg"],
                  command=add).pack(side="left", padx=10)
        tk.Button(btn_frame, text="Отмена", bg=t["btn_default_bg"], fg=t["btn_default_fg"],
                  activebackground=t["menu_active_bg"], activeforeground=t["menu_active_fg"],
                  command=dialog.destroy).pack(side="right", padx=10)

    def edit_repository_url(self, name):
        """Диалог для изменения URL репозитория."""
        t = self.THEMES.get(self.settings.get("theme", "Стандартная"))
        dialog = tk.Toplevel(self)
        dialog.title("Изменить URL")
        dialog.geometry("400x180")
        dialog.configure(bg=t["bg"])
        dialog.resizable(False, False)
        dialog.grab_set()

        tk.Label(dialog, text=f"URL репозитория '{name}':", bg=t["bg"], fg=t["fg"]).pack(pady=(15, 0))
        url_var = tk.StringVar(value=self.repositories[name]["url"])
        url_entry = tk.Entry(dialog, textvariable=url_var, bg=t["tree_bg"], fg=t["tree_fg"],
                             insertbackground=t["tree_fg"])
        url_entry.pack(pady=8, padx=20, fill="x")
        self._bind_paste(url_entry)

        def save():
            new_url = self._normalize_repo_url(url_var.get())
            if not new_url:
                messagebox.showerror("Ошибка", "Некорректный URL репозитория.", parent=dialog)
                return
            self.repositories[name]["url"] = new_url
            self.save_config()
            self.after_idle(self.refresh_builds_list)
            self.tree.selection_set(name)
            self.tree.see(name)
            self.log(f"URL репозитория '{name}' обновлён.", tag="info")
            dialog.destroy()

        btn_frame = tk.Frame(dialog, bg=t["bg"])
        btn_frame.pack(pady=15)
        tk.Button(btn_frame, text="Сохранить", bg=t["btn_accent_bg"], fg=t["btn_accent_fg"],
                  activebackground=t["menu_active_bg"], activeforeground=t["menu_active_fg"],
                  command=save).pack(side="left", padx=10)
        tk.Button(btn_frame, text="Отмена", bg=t["btn_default_bg"], fg=t["btn_default_fg"],
                  activebackground=t["menu_active_bg"], activeforeground=t["menu_active_fg"],
                  command=dialog.destroy).pack(side="right", padx=10)

    def rename_repository(self, name):
        """Диалог для переименования репозитория."""
        t = self.THEMES.get(self.settings.get("theme", "Стандартная"))
        dialog = tk.Toplevel(self)
        dialog.title("Переименовать сборку")
        dialog.geometry("400x180")
        dialog.configure(bg=t["bg"])
        dialog.resizable(False, False)
        dialog.grab_set()

        tk.Label(dialog, text="Новое имя сборки:", bg=t["bg"], fg=t["fg"]).pack(pady=(15, 0))
        name_var = tk.StringVar(value=name)
        name_entry = tk.Entry(dialog, textvariable=name_var, bg=t["tree_bg"], fg=t["tree_fg"],
                              insertbackground=t["tree_fg"])
        name_entry.pack(pady=8, padx=20, fill="x")
        self._bind_paste(name_entry)

        def save():
            new_name = name_var.get().strip()
            if not new_name or not re.match(r'^[\w\- ]+$', new_name):
                messagebox.showerror("Ошибка", "Некорректное имя сборки.", parent=dialog)
                return
            if new_name == name:
                dialog.destroy()
                return
            if new_name in self.repositories:
                messagebox.showerror("Ошибка", "Сборка с таким именем уже существует.", parent=dialog)
                return

            self.repositories[new_name] = self.repositories.pop(name)
            self.save_config()
            self.after_idle(self.refresh_builds_list)
            self.tree.selection_set(new_name)
            self.tree.see(new_name)
            self.log(f"Сборка '{name}' переименована в '{new_name}'.", tag="info")
            dialog.destroy()

        btn_frame = tk.Frame(dialog, bg=t["bg"])
        btn_frame.pack(pady=15)
        tk.Button(btn_frame, text="Сохранить", bg=t["btn_accent_bg"], fg=t["btn_accent_fg"],
                  activebackground=t["menu_active_bg"], activeforeground=t["menu_active_fg"],
                  command=save).pack(side="left", padx=10)
        tk.Button(btn_frame, text="Отмена", bg=t["btn_default_bg"], fg=t["btn_default_fg"],
                  activebackground=t["menu_active_bg"], activeforeground=t["menu_active_fg"],
                  command=dialog.destroy).pack(side="right", padx=10)

    def remove_repository_dialog(self):
        t = self.THEMES.get(self.settings.get("theme", "Стандартная"))
        if self._remove_repo_dialog is not None and self._remove_repo_dialog.winfo_exists():
            self._remove_repo_dialog.lift()
            return
        if not self.repositories:
            messagebox.showinfo("Информация", "Список репозиториев пуст.")
            return

        dialog = tk.Toplevel(self)
        self._remove_repo_dialog = dialog
        dialog.title("Удалить репозиторий")
        dialog.geometry("400x300")
        dialog.configure(bg=t["bg"])
        dialog.grab_set()
        dialog.protocol("WM_DELETE_WINDOW", lambda: self._on_remove_dialog_close(dialog))

        tk.Label(dialog, text="Выберите репозиторий для удаления:", bg=t["bg"], fg=t["fg"]).pack(pady=10)

        listbox = tk.Listbox(dialog, bg=t["tree_bg"], fg=t["tree_fg"],
                             selectbackground=t["tree_sel_bg"], selectforeground=t["fg"])
        listbox.pack(fill="both", expand=True, padx=20, pady=10)

        for name in self.repositories.keys():
            listbox.insert("end", name)

        def delete_selected():
            selection = listbox.curselection()
            if not selection:
                messagebox.showwarning("Удаление", "Выберите репозиторий.", parent=dialog)
                return
            name = listbox.get(selection[0])
            if messagebox.askyesno("Подтверждение", f"Удалить репозиторий '{name}' из списка?", parent=dialog):
                del self.repositories[name]
                self.save_config()
                self.after_idle(self.refresh_builds_list)
                self._on_remove_dialog_close(dialog)

        btn_frame = tk.Frame(dialog, bg=t["bg"])
        btn_frame.pack(fill="x", padx=20, pady=10)

        tk.Button(btn_frame, text="Удалить", bg=t["btn_danger_bg"], fg=t["btn_danger_fg"],
                  activebackground=t["menu_active_bg"], activeforeground=t["menu_active_fg"],
                  command=delete_selected).pack(side="left", padx=5)

        tk.Button(btn_frame, text="Отмена", bg=t["btn_default_bg"], fg=t["btn_default_fg"],
                  activebackground=t["menu_active_bg"], activeforeground=t["menu_active_fg"],
                  command=lambda: self._on_remove_dialog_close(dialog)).pack(side="right", padx=5)

    # ================== Вспомогательные методы ==================
    def _restore_config_confirm(self):
        if messagebox.askyesno("Восстановление конфигурации",
                               "Заменить текущий config.json резервной копией?\n"
                               "Текущие настройки будут потеряны."):
            if self.config_manager.restore_from_backup():
                self.repositories = self.config_manager.data.get("repositories", {})
                self.log_filters = self.config_manager.data.get("log_filters", {})
                self.settings = self.config_manager.data.get("settings", {})
                self.save_config()
                self.after_idle(self.refresh_builds_list)
                self.apply_theme(self.settings.get("theme", "Стандартная"))
                messagebox.showinfo("Готово", "Конфигурация восстановлена.")
            else:
                messagebox.showerror("Ошибка", "Резервная копия не найдена.")

    def _on_remove_dialog_close(self, dialog):
        dialog.grab_release()
        dialog.destroy()
        self._remove_repo_dialog = None

    def _close_settings_dialog(self, dialog):
        if self.settings_dialog == dialog:
            self.settings_dialog = None
            self.settings_notebook = None
            self.settings_widgets.clear()
            self.settings_tabs.clear()
        dialog.destroy()

    def _update_open_dialogs_theme(self, t):
        if self.settings_dialog is not None and self.settings_dialog.winfo_exists():
            self.settings_dialog.configure(bg=t["bg"])

            style = ttk.Style()
            style.configure("TNotebook", background=t["bg"], borderwidth=0, bordercolor=t["bg"])
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

            # Обновляем стиль Combobox с цветной рамкой
            style.configure("Console.TCombobox",
                            fieldbackground=t["tree_bg"],
                            background=t["tree_bg"],
                            foreground=t["tree_fg"],
                            arrowcolor=t["menu_fg"],
                            bordercolor=t["tree_frame_highlight"],
                            lightcolor=t["tree_bg"],
                            darkcolor=t["tree_bg"],
                            selectbackground=t["tree_sel_bg"],
                            selectforeground=t["tree_fg"],
                            focuscolor=t["menu_highlight"],
                            highlightthickness=1,
                            highlightbackground=t["tree_frame_highlight"],
                            highlightcolor=t["menu_highlight"],
                            borderwidth=1,
                            relief="solid")
            style.map("Console.TCombobox",
                      fieldbackground=[("readonly", t["tree_bg"]),
                                       ("focus", t["tree_bg"])],
                      foreground=[("readonly", t["tree_fg"]),
                                  ("focus", t["tree_fg"])],
                      background=[("readonly", t["tree_bg"])],
                      selectbackground=[("readonly", t["tree_sel_bg"])],
                      selectforeground=[("readonly", t["tree_fg"])],
                      bordercolor=[("focus", t["menu_highlight"])],
                      highlightcolor=[("focus", t["menu_highlight"])],
                      focuscolor=[("focus", t["menu_highlight"])])

            # Обновляем стиль выпадающего списка Combobox
            style.configure("Console.TCombobox.Listbox",
                            background=t["tree_bg"],
                            foreground=t["tree_fg"],
                            selectbackground=t["tree_sel_bg"],
                            selectforeground=t["tree_fg"],
                            borderwidth=0,
                            relief="flat",
                            highlightthickness=0)

            # Обновляем option_add
            self.option_add("*TCombobox*Listbox*Background", t["tree_bg"])
            self.option_add("*TCombobox*Listbox*Foreground", t["tree_fg"])
            self.option_add("*TCombobox*Listbox*selectBackground", t["tree_sel_bg"])
            self.option_add("*TCombobox*Listbox*selectForeground", t["tree_fg"])

            for tab in self.settings_tabs:
                if tab.winfo_exists():
                    tab.configure(bg=t["bg"])

            for widget in self.settings_widgets:
                if isinstance(widget, (tk.Checkbutton, tk.Radiobutton)):
                    widget.configure(bg=t["bg"], fg=t["fg"], selectcolor=t["bg"],
                                     activebackground=t["bg"], activeforeground=t["menu_fg"])
                elif isinstance(widget, tk.Spinbox):
                    widget.configure(bg=t["tree_bg"], fg=t["tree_fg"],
                                     buttonbackground=t["tree_bg"],
                                     insertbackground=t["tree_fg"])
                elif isinstance(widget, tk.Label):
                    widget.configure(bg=t["bg"], fg=t["fg"])
                elif isinstance(widget, tk.Frame):
                    widget.configure(bg=t["bg"])
                elif isinstance(widget, ttk.Combobox):
                    # Стиль уже обновлён, ничего дополнительно не требуется
                    pass
                elif isinstance(widget, tk.Button):
                    if widget.cget("text") == "Сохранить":
                        bg, fg = t["btn_accent_bg"], t["btn_accent_fg"]
                    elif widget.cget("text") == "По умолчанию":
                        bg, fg = t["btn_default_bg"], t["btn_default_fg"]
                    elif widget.cget("text") == "Отмена":
                        bg, fg = t["btn_default_bg"], t["btn_default_fg"]
                    else:
                        bg, fg = t["btn_default_bg"], t["btn_default_fg"]
                    widget.configure(bg=bg, fg=fg,
                                     activebackground=t["menu_active_bg"],
                                     activeforeground=t["menu_active_fg"])

        if self._repo_menu_window is not None and self._repo_menu_window.winfo_exists():
            self._repo_menu_window.configure(bg=t["menu_bg"])
            for child in self._repo_menu_window.winfo_children():
                if isinstance(child, tk.Button):
                    child.configure(bg=t["menu_bg"], fg=t["menu_fg"],
                                    activebackground=t["menu_active_bg"],
                                    activeforeground=t["menu_active_fg"])