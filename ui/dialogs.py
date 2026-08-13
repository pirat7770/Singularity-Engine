# ui/dialogs.py
import tkinter as tk
from tkinter import ttk, messagebox
import os
import shutil
import re
import time
from pathlib import Path
import sys

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
    def open_settings_dialog(self):
        original_theme = self.settings.get("theme", "Стандартная")
        t = self.THEMES.get(original_theme)

        if self.settings_dialog is not None and self.settings_dialog.winfo_exists():
            self.settings_dialog.lift()
            return

        dialog = tk.Toplevel(self)
        self.settings_dialog = dialog
        dialog.title("Настройки")
        dialog.geometry("560x600")
        dialog.configure(bg=t["bg"])
        dialog.resizable(False, False)
        dialog.grab_set()
        dialog.protocol("WM_DELETE_WINDOW", lambda: save())

        notebook = ttk.Notebook(dialog)
        self.settings_notebook = notebook
        style = ttk.Style()
        style.configure("TNotebook", background=t["bg"], borderwidth=0)
        style.configure("TNotebook.Tab", background=t["tree_bg"], foreground=t["tree_fg"],
                        padding=[10, 5], bordercolor=t["tree_frame_highlight"])
        style.map("TNotebook.Tab",
                  background=[("selected", t["bg"])],
                  foreground=[("selected", t["menu_fg"])],
                  bordercolor=[("selected", t["menu_highlight"])])
        notebook.pack(fill="both", expand=True, padx=5, pady=5)

        self.settings_widgets.clear()
        self.settings_tabs.clear()

        # Вкладка "Общие"
        tab_general = tk.Frame(notebook, bg=t["bg"])
        notebook.add(tab_general, text="Общие")
        self.settings_tabs.append(tab_general)

        keep_finished_var = tk.BooleanVar(value=self.settings.get("keep_finished_instances", True))
        keep_finished_check = tk.Checkbutton(tab_general,
                                             text="Сохранять завершённые экземпляры в списке",
                                             variable=keep_finished_var, bg=t["bg"], fg=t["fg"],
                                             selectcolor=t["bg"],
                                             activebackground=t["bg"], activeforeground=t["menu_fg"])
        keep_finished_check.pack(anchor="w", padx=20, pady=5)
        self.settings_widgets.append(keep_finished_check)
        ToolTip(keep_finished_check,
                "Если включено, завершившиеся экземпляры остаются в диспетчере для просмотра логов.\n"
                "Если выключено, они автоматически удаляются.")

        max_inst_var = tk.IntVar(value=self.settings.get("max_instances", 5))
        max_inst_frame = tk.Frame(tab_general, bg=t["bg"])
        max_inst_frame.pack(anchor="w", padx=20, pady=5)
        max_inst_label = tk.Label(max_inst_frame, text="Максимум экземпляров одной сборки:", bg=t["bg"], fg=t["fg"])
        max_inst_label.pack(side="left")
        self.settings_widgets.append(max_inst_label)
        max_inst_spin = tk.Spinbox(max_inst_frame, from_=1, to=10, width=3, textvariable=max_inst_var,
                                   bg=t["tree_bg"], fg=t["tree_fg"], buttonbackground=t["tree_bg"],
                                   insertbackground=t["tree_fg"])
        max_inst_spin.pack(side="left", padx=5)
        ToolTip(max_inst_spin, "Сколько одновременных копий одной сборки можно запустить.")
        self.settings_widgets.extend([max_inst_spin, max_inst_frame])

        auto_del_var = tk.BooleanVar(value=self.settings.get("auto_delete_failed", False))
        confirm_clean_var = tk.BooleanVar(value=self.settings.get("confirm_clean_rebuild", False))
        shallow_var = tk.BooleanVar(value=self.settings.get("shallow_clone", False))
        parallel_var = tk.BooleanVar(value=self.settings.get("parallel_build", False))
        pre_restore_var = tk.BooleanVar(value=self.settings.get("pre_restore", False))
        strict_sdk_var = tk.BooleanVar(value=self.settings.get("strict_sdk_major", True))
        auto_deps_var = tk.BooleanVar(value=self.settings.get("auto_install_deps", False))
        confirm_destructive_var = tk.BooleanVar(value=self.settings.get("confirm_destructive", True))

        # Кнопка очистки кэша
        clear_cache_btn = tk.Button(tab_general, text="Очистить кэш",
                                    bg=t["btn_danger_bg"], fg=t["btn_danger_fg"],
                                    activebackground=t["menu_active_bg"], activeforeground=t["menu_active_fg"],
                                    command=self.clear_cache)
        clear_cache_btn.pack(anchor="w", padx=20, pady=5)
        self.settings_widgets.append(clear_cache_btn)

        # Чекбоксы
        auto_del_check = tk.Checkbutton(tab_general, text="Автоматически удалять неудавшиеся сборки",
                                        variable=auto_del_var, bg=t["bg"], fg=t["fg"], selectcolor=t["bg"],
                                        activebackground=t["bg"], activeforeground=t["menu_fg"])
        auto_del_check.pack(anchor="w", padx=20, pady=5)
        ToolTip(auto_del_check, "Если включено, после ошибки сборки папка будет удалена.\n"
                                "Если выключено, папка остаётся для повторного использования.")
        self.settings_widgets.append(auto_del_check)

        confirm_clean_check = tk.Checkbutton(tab_general, text="Запрашивать подтверждение перед очисткой кэша",
                                             variable=confirm_clean_var, bg=t["bg"], fg=t["fg"], selectcolor=t["bg"],
                                             activebackground=t["bg"], activeforeground=t["menu_fg"])
        confirm_clean_check.pack(anchor="w", padx=20, pady=5)
        ToolTip(confirm_clean_check, "Показывать диалог подтверждения перед выполнением\n"
                                     "глубокой очистки (bin, obj) и пересборки.")
        self.settings_widgets.append(confirm_clean_check)

        shallow_check = tk.Checkbutton(tab_general, text="Мелкое клонирование (shallow clone)",
                                       variable=shallow_var, bg=t["bg"], fg=t["fg"], selectcolor=t["bg"],
                                       activebackground=t["bg"], activeforeground=t["menu_fg"])
        shallow_check.pack(anchor="w", padx=20, pady=5)
        ToolTip(shallow_check, "Использовать git clone --depth 1 для ускорения загрузки.\n"
                               "Не скачивается вся история коммитов.")
        self.settings_widgets.append(shallow_check)

        pre_restore_check = tk.Checkbutton(tab_general, text="Предварительное восстановление пакетов (dotnet restore)",
                                           variable=pre_restore_var, bg=t["bg"], fg=t["fg"], selectcolor=t["bg"],
                                           activebackground=t["bg"], activeforeground=t["menu_fg"])
        pre_restore_check.pack(anchor="w", padx=20, pady=5)
        ToolTip(pre_restore_check, "Запускать dotnet restore перед сборкой.\n"
                                   "Может ускорить последующие сборки за счёт кэширования пакетов.")
        self.settings_widgets.append(pre_restore_check)

        parallel_check = tk.Checkbutton(tab_general, text="Параллельная сборка (dotnet build -m)",
                                        variable=parallel_var, bg=t["bg"], fg=t["fg"], selectcolor=t["bg"],
                                        activebackground=t["bg"], activeforeground=t["menu_fg"])
        parallel_check.pack(anchor="w", padx=20, pady=5)
        ToolTip(parallel_check, "Включить многопоточную сборку MSBuild.\n"
                                "Ускоряет компиляцию на многоядерных процессорах.")
        self.settings_widgets.append(parallel_check)

        strict_sdk_check = tk.Checkbutton(tab_general, text="Строго соблюдать основную версию SDK (не подменять major)",
                                          variable=strict_sdk_var, bg=t["bg"], fg=t["fg"], selectcolor=t["bg"],
                                          activebackground=t["bg"], activeforeground=t["menu_fg"])
        strict_sdk_check.pack(anchor="w", padx=20, pady=5)
        ToolTip(strict_sdk_check, "Если включено, программа не будет заменять требуемую major-версию SDK\n"
                                  "на другую (например, 9.0 не заменится на 10.0).\n"
                                  "Если выключено, попытается подобрать ближайшую старшую версию.")
        self.settings_widgets.append(strict_sdk_check)

        auto_deps_check = tk.Checkbutton(tab_general, text="Автоматически устанавливать недостающие зависимости",
                                         variable=auto_deps_var, bg=t["bg"], fg=t["fg"], selectcolor=t["bg"],
                                         activebackground=t["bg"], activeforeground=t["menu_fg"])
        auto_deps_check.pack(anchor="w", padx=20, pady=5)
        ToolTip(auto_deps_check, "Не спрашивать разрешения на установку Git, Python и .NET SDK.\n"
                                 "Скачивание и запуск установщиков будет выполняться автоматически.")
        self.settings_widgets.append(auto_deps_check)

        confirm_destructive_check = tk.Checkbutton(tab_general,
                                                   text="Подтверждать опасные действия (удаление, переустановка)",
                                                   variable=confirm_destructive_var, bg=t["bg"], fg=t["fg"],
                                                   selectcolor=t["bg"],
                                                   activebackground=t["bg"], activeforeground=t["menu_fg"])
        confirm_destructive_check.pack(anchor="w", padx=20, pady=5)
        ToolTip(confirm_destructive_check, "Показывать подтверждение перед удалением или переустановкой сборки.\n"
                                           "Защищает от случайных кликов.")
        self.settings_widgets.append(confirm_destructive_check)

        restore_btn = tk.Button(tab_general, text="Восстановить конфигурацию из резервной копии",
                                bg=t["btn_default_bg"], fg=t["btn_default_fg"],
                                activebackground=t["menu_active_bg"], activeforeground=t["menu_active_fg"],
                                command=self._restore_config_confirm)
        restore_btn.pack(anchor="w", padx=20, pady=10)
        self.settings_widgets.append(restore_btn)

        # Вкладка "Оформление"
        tab_theme = tk.Frame(notebook, bg=t["bg"])
        notebook.add(tab_theme, text="Оформление")
        self.settings_tabs.append(tab_theme)

        theme_label = tk.Label(tab_theme, text="Выберите тему:", bg=t["bg"], fg=t["fg"], font=("Arial", 10))
        theme_label.pack(pady=10)
        self.settings_widgets.append(theme_label)

        current_theme = tk.StringVar(value=original_theme)
        theme_radios = []
        for name in self.THEMES:
            rb = tk.Radiobutton(tab_theme, text=name, variable=current_theme, value=name,
                                bg=t["bg"], fg=t["fg"], selectcolor=t["bg"],
                                activebackground=t["bg"], activeforeground=t["menu_fg"],
                                command=lambda n=name: self.apply_theme(n))
            rb.pack(anchor="w", padx=20, pady=3)
            theme_radios.append(rb)

        # Вкладка "Инструменты"
        tab_tools = tk.Frame(notebook, bg=t["bg"])
        notebook.add(tab_tools, text="Инструменты")
        self.settings_tabs.append(tab_tools)

        def build_tool_row(parent, label_text, check_func, install_cmd):
            row = tk.Frame(parent, bg=t["bg"])
            row.pack(fill="x", padx=20, pady=8)
            status = "✅ Установлен" if check_func() else "❌ Не установлен"
            fg_color = t["btn_accent_fg"] if check_func() else t["btn_danger_fg"]
            lbl = tk.Label(row, text=f"{label_text}: {status}", bg=t["bg"], fg=fg_color)
            lbl.pack(side="left")
            btn = tk.Button(row, text="Установить/Переустановить",
                            bg=t["btn_accent_bg"], fg=t["btn_accent_fg"],
                            activebackground=t["menu_active_bg"], activeforeground=t["menu_active_fg"],
                            command=install_cmd)
            btn.pack(side="right")
            self.settings_widgets.extend([row, lbl, btn])
            return row, lbl, btn

        build_tool_row(tab_tools, "Git",
                       lambda: self._is_tool_installed("git"),
                       lambda: self._download_and_run_installer("Git", self._get_git_url()))
        build_tool_row(tab_tools, "Python",
                       lambda: self._is_python_installed(),
                       self._offer_python_install)

        def check_dotnet():
            if not self._is_tool_installed("dotnet"):
                return False
            installed = self._get_installed_sdks()
            return any(v.startswith("9.") or v.startswith("10.") for v in installed)

        build_tool_row(tab_tools, ".NET SDK 9/10",
                       check_dotnet,
                       lambda: self._download_and_install_sdk("10.0.302", None, None))

        logs_btn = tk.Button(tab_tools, text="Открыть папку с логами",
                             bg=t["btn_default_bg"], fg=t["btn_default_fg"],
                             activebackground=t["menu_active_bg"], activeforeground=t["menu_active_fg"],
                             command=self.open_logs_folder)
        logs_btn.pack(pady=10)
        self.settings_widgets.append(logs_btn)

        # Кнопки внизу
        btn_frame = tk.Frame(dialog, bg=t["bg"])
        btn_frame.pack(pady=10)

        def save():
            self.settings["auto_delete_failed"] = auto_del_var.get()
            self.settings["confirm_clean_rebuild"] = confirm_clean_var.get()
            self.settings["shallow_clone"] = shallow_var.get()
            self.settings["parallel_build"] = parallel_var.get()
            self.settings["pre_restore"] = pre_restore_var.get()
            self.settings["strict_sdk_major"] = strict_sdk_var.get()
            self.settings["auto_install_deps"] = auto_deps_var.get()
            self.settings["confirm_destructive"] = confirm_destructive_var.get()
            self.settings["keep_finished_instances"] = keep_finished_var.get()
            self.settings["max_instances"] = max_inst_var.get()
            self.settings["theme"] = current_theme.get()
            self.save_settings()
            self._close_settings_dialog(dialog)

        def reset():
            auto_del_var.set(False)
            confirm_clean_var.set(False)
            shallow_var.set(False)
            parallel_var.set(False)
            pre_restore_var.set(False)
            strict_sdk_var.set(True)
            auto_deps_var.set(False)
            confirm_destructive_var.set(True)
            keep_finished_var.set(True)
            max_inst_var.set(5)
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

        self.settings_widgets.extend([auto_del_check, confirm_clean_check, shallow_check,
                                      pre_restore_check, parallel_check, strict_sdk_check,
                                      auto_deps_check, confirm_destructive_check])
        self.settings_widgets.extend(theme_radios)
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
        if git_cache_dir.exists():
            try:
                shutil.rmtree(git_cache_dir)
                self.log("🧹 Git-кэш очищен.", tag="success")
            except Exception as e:
                self.log(f"❌ Не удалось очистить git-кэш: {e}", tag="error")
        else:
            self.log("ℹ Git-кэш уже пуст.", tag="info")

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
        tk.Entry(dialog, textvariable=name_var, bg=t["tree_bg"], fg=t["tree_fg"],
                 insertbackground=t["tree_fg"]).pack(pady=5, padx=20, fill="x")

        tk.Label(dialog, text="Git URL:", bg=t["bg"], fg=t["fg"]).pack(pady=(5, 0))
        url_var = tk.StringVar()
        tk.Entry(dialog, textvariable=url_var, bg=t["tree_bg"], fg=t["tree_fg"],
                 insertbackground=t["tree_fg"]).pack(pady=5, padx=20, fill="x")

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
        tk.Entry(dialog, textvariable=prebuilt_var, bg=t["tree_bg"], fg=t["tree_fg"],
                 insertbackground=t["tree_fg"]).pack(pady=5, padx=20, fill="x")

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
                return
            name = listbox.get(selection[0])
            if messagebox.askyesno("Подтверждение", f"Удалить репозиторий '{name}' из списка?", parent=dialog):
                del self.repositories[name]
                self.save_config()
                self.refresh_builds_list()
                self._on_remove_dialog_close(dialog)

        btn_frame = tk.Frame(dialog, bg=t["bg"])
        btn_frame.pack(pady=5)
        tk.Button(btn_frame, text="Удалить", bg=t["btn_danger_bg"], fg=t["btn_danger_fg"],
                  activebackground=t["menu_active_bg"], activeforeground=t["menu_active_fg"],
                  command=delete_selected).pack(side="left", padx=10)
        tk.Button(btn_frame, text="Отмена", bg=t["btn_default_bg"], fg=t["btn_default_fg"],
                  activebackground=t["menu_active_bg"], activeforeground=t["menu_active_fg"],
                  command=lambda: self._on_remove_dialog_close(dialog)).pack(side="right", padx=10)

    def rename_repository(self, old_name):
        if old_name not in self.repositories:
            return
        if self.get_build_status(old_name) in self.BUSY_STATUSES or self._is_game_running(old_name):
            messagebox.showwarning("Недоступно", "Дождитесь завершения операции или остановите игру.")
            return

        dialog = tk.Toplevel(self)
        dialog.title("Переименовать репозиторий")
        dialog.geometry("350x150")
        dialog.configure(bg=self._get_theme_color("bg"))
        dialog.resizable(False, False)
        dialog.grab_set()

        tk.Label(dialog, text="Новое имя:", bg=self._get_theme_color("bg"),
                 fg=self._get_theme_color("fg")).pack(pady=(15, 5))
        new_name_var = tk.StringVar(value=old_name)
        entry = tk.Entry(dialog, textvariable=new_name_var, bg=self._get_theme_color("tree_bg"),
                         fg=self._get_theme_color("tree_fg"), insertbackground=self._get_theme_color("tree_fg"))
        entry.pack(padx=20, fill="x")
        entry.select_range(0, tk.END)
        entry.focus_set()

        def do_rename():
            new_name = new_name_var.get().strip()
            if not new_name or new_name == old_name:
                dialog.destroy()
                return
            if new_name in self.repositories:
                messagebox.showerror("Ошибка", "Репозиторий с таким именем уже существует.", parent=dialog)
                return
            if not re.match(r'^[\w\- ]+$', new_name):
                messagebox.showerror("Ошибка", "Имя содержит недопустимые символы.", parent=dialog)
                return

            repo_data = self.repositories.pop(old_name)
            self.repositories[new_name] = repo_data

            old_path = os.path.join(self.builds_dir, old_name)
            new_path = os.path.join(self.builds_dir, new_name)
            if os.path.exists(old_path):
                try:
                    os.rename(old_path, new_path)
                except Exception as e:
                    self.log(f"⚠ Не удалось переименовать папку: {e}", tag="warn")
                    messagebox.showwarning("Внимание",
                                           f"Запись обновлена, но папку '{old_name}' не удалось переименовать.\n"
                                           f"Проверьте права доступа или закройте использующие её программы.",
                                           parent=dialog)

            self.save_config()
            self.refresh_builds_list()
            self.tree.selection_set(new_name)
            self.tree.see(new_name)
            self.log(f"✏ Репозиторий переименован: {old_name} → {new_name}", tag="info")
            dialog.destroy()

        btn_frame = tk.Frame(dialog, bg=self._get_theme_color("bg"))
        btn_frame.pack(pady=15)
        tk.Button(btn_frame, text="ОК", bg=self._get_theme_color("btn_accent_bg"),
                  fg=self._get_theme_color("btn_accent_fg"),
                  activebackground=self._get_theme_color("menu_active_bg"),
                  activeforeground=self._get_theme_color("menu_active_fg"),
                  command=do_rename).pack(side="left", padx=10)
        tk.Button(btn_frame, text="Отмена", bg=self._get_theme_color("btn_default_bg"),
                  fg=self._get_theme_color("btn_default_fg"),
                  activebackground=self._get_theme_color("menu_active_bg"),
                  activeforeground=self._get_theme_color("menu_active_fg"),
                  command=dialog.destroy).pack(side="right", padx=10)

    def edit_repository_url(self, name):
        if name not in self.repositories:
            return

        dialog = tk.Toplevel(self)
        dialog.title(f"Изменить URL: {name}")
        dialog.geometry("450x150")
        dialog.configure(bg=self._get_theme_color("bg"))
        dialog.resizable(False, False)
        dialog.grab_set()

        tk.Label(dialog, text="Новый Git URL:", bg=self._get_theme_color("bg"),
                 fg=self._get_theme_color("fg")).pack(pady=(15, 5))
        url_var = tk.StringVar(value=self.repositories[name].get("url", ""))
        entry = tk.Entry(dialog, textvariable=url_var, width=50,
                         bg=self._get_theme_color("tree_bg"),
                         fg=self._get_theme_color("tree_fg"),
                         insertbackground=self._get_theme_color("tree_fg"))
        entry.pack(padx=20, pady=5)

        def save_url():
            new_url = url_var.get().strip()
            if not re.match(r'^(https?|git)://.+\..+', new_url):
                messagebox.showerror("Ошибка", "Введите корректный Git URL.", parent=dialog)
                return
            self.repositories[name]["url"] = new_url
            self.save_config()
            self.log(f"🔗 URL для '{name}' обновлён.", tag="info")
            dialog.destroy()

        btn_frame = tk.Frame(dialog, bg=self._get_theme_color("bg"))
        btn_frame.pack(pady=15)
        tk.Button(btn_frame, text="Сохранить", bg=self._get_theme_color("btn_accent_bg"),
                  fg=self._get_theme_color("btn_accent_fg"),
                  activebackground=self._get_theme_color("menu_active_bg"),
                  activeforeground=self._get_theme_color("menu_active_fg"),
                  command=save_url).pack(side="left", padx=10)
        tk.Button(btn_frame, text="Отмена", bg=self._get_theme_color("btn_default_bg"),
                  fg=self._get_theme_color("btn_default_fg"),
                  activebackground=self._get_theme_color("menu_active_bg"),
                  activeforeground=self._get_theme_color("menu_active_fg"),
                  command=dialog.destroy).pack(side="right", padx=10)
        refresh_list()

        def restore_selected():
            selection = listbox.curselection()
            if not selection:
                messagebox.showwarning("Корзина", "Выберите элемент для восстановления.", parent=dialog)
                return
            item_name = listbox.get(selection[0])
            if messagebox.askyesno("Восстановить", f"Восстановить '{item_name}'?", parent=dialog):
                if self.restore_from_trash(item_name):
                    self.log(f"🔄 Восстановлена сборка: {item_name}", tag="success")
                    refresh_list()
                    self.refresh_builds_list()
                else:
                    messagebox.showerror("Ошибка", "Не удалось восстановить (возможно, папка с таким именем уже существует).",
                                         parent=dialog)

        def delete_selected():
            selection = listbox.curselection()
            if not selection:
                messagebox.showwarning("Корзина", "Выберите элемент для удаления.", parent=dialog)
                return
            item_name = listbox.get(selection[0])
            if messagebox.askyesno("Удалить безвозвратно", f"Удалить '{item_name}' из корзины?\nДействие необратимо.",
                                   parent=dialog):
                if self.delete_trash_item(item_name):
                    self.log(f"🗑 Из корзины удалено: {item_name}", tag="success")
                    refresh_list()
                else:
                    messagebox.showerror("Ошибка", "Не удалось удалить элемент.", parent=dialog)

        def clear_trash():
            if messagebox.askyesno("Очистить корзину", "Удалить все элементы из корзины безвозвратно?",
                                   parent=dialog):
                self.clear_trash_folder()
                refresh_list()

        btn_frame = tk.Frame(dialog, bg=t["bg"])
        btn_frame.pack(fill="x", padx=10, pady=10)

        tk.Button(btn_frame, text="Восстановить", bg=t["btn_accent_bg"], fg=t["btn_accent_fg"],
                  activebackground=t["menu_active_bg"], activeforeground=t["menu_active_fg"],
                  command=restore_selected).pack(side="left", padx=5)
        tk.Button(btn_frame, text="Удалить", bg=t["btn_danger_bg"], fg=t["btn_danger_fg"],
                  activebackground=t["menu_active_bg"], activeforeground=t["menu_active_fg"],
                  command=delete_selected).pack(side="left", padx=5)
        tk.Button(btn_frame, text="Очистить всё", bg=t["btn_danger_bg"], fg=t["btn_danger_fg"],
                  activebackground=t["menu_active_bg"], activeforeground=t["menu_active_fg"],
                  command=clear_trash).pack(side="left", padx=5)
        tk.Button(btn_frame, text="Открыть папку", bg=t["btn_default_bg"], fg=t["btn_default_fg"],
                  activebackground=t["menu_active_bg"], activeforeground=t["menu_active_fg"],
                  command=self.open_trash_folder).pack(side="right", padx=5)

    def clear_download_cache(self):
        cache_dir = self.download_manager.cache_dir
        if not cache_dir.exists():
            messagebox.showinfo("Кэш", "Кэш загрузок пуст.")
            return
        if messagebox.askyesno("Очистить кэш загрузок", "Удалить все кэшированные установщики и временные файлы?"):
            try:
                shutil.rmtree(cache_dir)
                cache_dir.mkdir(parents=True, exist_ok=True)
                self.log("🧹 Кэш загрузок очищен.", tag="success")
            except Exception as e:
                self.log(f"❌ Не удалось очистить кэш: {e}", tag="error")

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