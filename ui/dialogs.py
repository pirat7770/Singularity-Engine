# ui/dialogs.py
import tkinter as tk
from tkinter import ttk, messagebox
import os
import shutil
import re
import time
from pathlib import Path
import sys
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
        dialog.geometry("620x680")
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

        # ===== Вкладка "Инструменты" =====
        tab_tools = tk.Frame(notebook, bg=t["bg"])
        notebook.add(tab_tools, text="Инструменты")
        self.settings_tabs.append(tab_tools)

        section = add_section(tab_tools, "Необходимые компоненты")

        def build_tool_row(parent, label_text, check_func, install_cmd):
            row = tk.Frame(parent, bg=t["bg"])
            row.pack(fill="x", padx=10, pady=6)
            status = "✅ Установлен" if check_func() else "❌ Не установлен"
            fg = t["btn_accent_fg"] if check_func() else t["btn_danger_fg"]
            lbl = tk.Label(row, text=f"{label_text}: {status}", bg=t["bg"], fg=fg)
            lbl.pack(side="left")
            btn = tk.Button(row, text="Установить/Переустановить",
                            bg=t["btn_accent_bg"], fg=t["btn_accent_fg"],
                            activebackground=t["menu_active_bg"], activeforeground=t["menu_active_fg"],
                            command=install_cmd)
            btn.pack(side="right")
            self.settings_widgets.extend([row, lbl, btn])
            return row, lbl, btn

        build_tool_row(section, "Git",
                       lambda: self._is_tool_installed("git"),
                       lambda: self._download_and_run_installer("Git", self._get_git_url()))
        build_tool_row(section, "Python",
                       lambda: self._is_python_installed(),
                       lambda: self._download_and_run_installer("Python", self._get_python_installer_url()))

        def check_dotnet():
            if not self._is_tool_installed("dotnet"):
                return False
            installed = self._get_installed_sdks()
            return any(v.startswith("9.") or v.startswith("10.") for v in installed)

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
            self.settings["auto_delete_failed"] = auto_del_var.get()
            self.settings["confirm_clean_rebuild"] = confirm_clean_var.get()
            self.settings["shallow_clone"] = shallow_var.get()
            self.settings["parallel_build"] = parallel_var.get()
            self.settings["pre_restore"] = pre_restore_var.get()
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
            self.save_settings()
            self.log("Настройки сохранены.", tag="info")
            self._close_settings_dialog(dialog)

        def reset():
            auto_del_var.set(False)
            confirm_clean_var.set(False)
            shallow_var.set(False)
            auto_update_var.set(False)
            parallel_var.set(False)
            pre_restore_var.set(False)
            strict_sdk_var.set(True)
            auto_deps_var.set(False)
            confirm_destructive_var.set(True)
            keep_finished_var.set(True)
            max_inst_var.set(5)
            builds_dir_var.set("")
            verify_signature_var.set(True)
            current_theme.set("Стандартная")
            self.apply_theme("Стандартная")

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
        """Очищает весь кэш: установщики и git-объекты."""
        # Очистка кэша установщиков
        self.clear_download_cache()

        # Очистка git-кэша
        git_cache_dir = Path(self.builds_dir) / ".git_cache"
        if not git_cache_dir.exists():
            self.log("ℹ Git-кэш уже пуст.", tag="info")
            return

        # Завершаем процессы, которые могут держать файлы кэша
        self.kill_processes_locking_folder(str(git_cache_dir))
        time.sleep(0.5)  # небольшая пауза для освобождения файлов

        # Пробуем удалить через shutil (быстро)
        try:
            shutil.rmtree(git_cache_dir, ignore_errors=True)
            if not git_cache_dir.exists():
                self.log("🧹 Git-кэш очищен.", tag="success")
                return
        except Exception:
            pass

        # Если не удалось, пробуем через cmd
        if sys.platform == "win32":
            try:
                subprocess.run(
                    ["cmd", "/c", "rmdir", "/s", "/q", str(git_cache_dir)],
                    capture_output=True, timeout=10,
                    startupinfo=self._hidden_startupinfo(),
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
                )
                if not git_cache_dir.exists():
                    self.log("🧹 Git-кэш очищен через cmd.", tag="success")
                    return
            except Exception:
                pass

        # Если всё ещё не удалилось, сообщаем об ошибке
        self.log("❌ Не удалось очистить git-кэш: файлы заняты другим процессом.", tag="error")

    def clear_download_cache(self):
        """Очищает только кэш установщиков."""
        cache_dir = self.download_manager.cache_dir
        if not cache_dir.exists():
            messagebox.showinfo("Кэш", "Кэш загрузок пуст.")
            return
        if messagebox.askyesno("Очистить кэш загрузок", "Удалить все кэшированные установщики?"):
            try:
                shutil.rmtree(cache_dir)
                cache_dir.mkdir(parents=True, exist_ok=True)
                self.log("🧹 Кэш установщиков очищен.", tag="success")
            except Exception as e:
                self.log(f"❌ Не удалось очистить кэш установщиков: {e}", tag="error")

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
        name_entry.bind("<Control-v>", lambda e: name_entry.event_generate("<<Paste>>"))
        name_entry.bind("<Control-V>", lambda e: name_entry.event_generate("<<Paste>>"))

        tk.Label(dialog, text="Git URL:", bg=t["bg"], fg=t["fg"]).pack(pady=(5, 0))
        url_var = tk.StringVar()
        url_entry = tk.Entry(dialog, textvariable=url_var, bg=t["tree_bg"], fg=t["tree_fg"],
                             insertbackground=t["tree_fg"])
        url_entry.pack(pady=5, padx=20, fill="x")
        url_entry.bind("<Control-v>", lambda e: url_entry.event_generate("<<Paste>>"))
        url_entry.bind("<Control-V>", lambda e: url_entry.event_generate("<<Paste>>"))

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
        prebuilt_entry.bind("<Control-v>", lambda e: prebuilt_entry.event_generate("<<Paste>>"))
        prebuilt_entry.bind("<Control-V>", lambda e: prebuilt_entry.event_generate("<<Paste>>"))

        def add():
            name = name_var.get().strip()
            url = url_var.get().strip()
            if not name or not re.match(r'^[\w\- ]+$', name) or name in self.repositories or not url or not re.match(
                    r'^(https?|git)://.+\..+', url):
                messagebox.showerror("Ошибка", "Проверьте правильность введённых данных.", parent=dialog)
                return
            repo_data = {"url": url, "mode": mode_var.get(), "favorite": False}
            if prebuilt_var.get().strip():
                repo_data["prebuilt_url"] = prebuilt_var.get().strip()
            self.repositories[name] = repo_data
            self.save_config()
            self.refresh_builds_list()
            dialog.destroy()

        btn_frame = tk.Frame(dialog, bg=t["bg"])
        btn_frame.pack(pady=15)
        tk.Button(btn_frame, text="Добавить", bg=t["btn_accent_bg"], fg=t["btn_accent_fg"],
                  activebackground=t["menu_active_bg"], activeforeground=t["menu_active_fg"],
                  command=add).pack(side="left", padx=10)
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
                self.refresh_builds_list()
                self._on_remove_dialog_close(dialog)

        # Кнопки
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
                self.refresh_builds_list()
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
