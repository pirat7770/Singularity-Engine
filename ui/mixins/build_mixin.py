# ui/mixins/build_mixin.py
import os
import sys
import time
import json
import shutil
import threading
import subprocess
from pathlib import Path
from tkinter import messagebox

import zipfile


class BuildMixin:
    """Методы сборки, установки и управления проектами."""

    # ================== Установка ==================

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
            self._configure_git_for_stability()
            clone_success = False
            git_cache_path = self._get_git_cache_dir() / name

            # 1) Пытаемся клонировать с git-кэшем, если он есть
            if git_cache_path.exists():
                clone_cmd = ["git", "clone", "--progress",
                             "--reference", str(git_cache_path), "--dissociate"]
                if self.settings.get("shallow_clone", False):
                    clone_cmd += ["--depth", "1"]
                clone_cmd += [repo_url, str(build_path)]

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

            if self._download_cancel_event.is_set() or self._cancel_download:
                self.log("🛑 Установка отменена пользователем.", tag="warn")
                self.after(0, lambda: self._end_operation(name))
                self.after(0, self._install_failed, name, build_path)
                return

            # 2) Клонируем обычным способом (с повторами)
            if not clone_success:
                clone_cmd = ["git", "clone", "--progress"]
                if self.settings.get("shallow_clone", False):
                    clone_cmd += ["--depth", "1"]
                clone_cmd += [repo_url, str(build_path)]

                max_attempts = 3
                for attempt in range(1, max_attempts + 1):
                    if os.path.exists(build_path):
                        self.log(f"🧹 Очистка неполной папки перед попыткой {attempt}...", tag="info")
                        self._fast_remove_folder(build_path, name)

                    clone_success = self._run_subprocess(
                        clone_cmd, cwd=None,
                        step_name="git clone",
                        progress_parser=self.filter_git_line,
                        operation_name=name
                    )
                    if clone_success:
                        break
                    if self._cancel_download:
                        break
                    if attempt < max_attempts:
                        self.log(f"⚠ Попытка {attempt} не удалась. Повтор через 5 секунд...", tag="warn")
                        time.sleep(5)

            if not clone_success:
                self._log_clone_failure_help()
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
                        if req_sdk in installed:
                            self.log(f"✅ Требуемая SDK {req_sdk} найдена.", tag="success")
                        else:
                            best = self._get_best_installed_sdk(req_sdk)
                            if best is not None:
                                self.log(f"⚠ Требуемая SDK {req_sdk} не найдена. Заменяем на {best}.", tag="warn")
                                data["sdk"]["version"] = best
                                with open(global_json, "w", encoding="utf-8") as f:
                                    json.dump(data, f, indent=2)
                                self.log("✅ global.json обновлён.", tag="success")
                            else:
                                self.log(f"❌ Нет подходящей SDK. Требуется {req_sdk}.", tag="error")
                                if self._offer_sdk_install_before_build(req_sdk, name, build_path):
                                    # Ждём, пока SDK установится (максимум 5 минут)
                                    deadline = time.time() + 300
                                    while time.time() < deadline:
                                        installed = self._get_installed_sdks()
                                        if req_sdk in installed:
                                            break
                                        time.sleep(5)
                                    installed = self._get_installed_sdks()
                                    if req_sdk not in installed:
                                        self.log("❌ Установка SDK не завершилась или версия не появилась.",
                                                 tag="error")
                                        self.after(0, lambda: self._end_operation(name))
                                        self.after(0, self._install_failed, name, build_path)
                                        return
                                    # После успешной установки пробуем обновить global.json
                                    self._fix_dotnet_sdk(global_json)
                                else:
                                    self.log("⚠ Сборка отменена из-за отсутствия SDK.", tag="warn")
                                    self.after(0, lambda: self._end_operation(name))
                                    self.after(0, self._install_failed, name, build_path)
                                    return
                except Exception as e:
                    self.log(f"⚠ Ошибка обработки global.json: {e}", tag="warn")

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

    # ================== Продолжение сборки и обработка ошибок ==================

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
        self.notify_tray("Ошибка", f"Сборка '{name}' не удалась.")
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
            except Exception as e:
                self.log(f"⚠ Не удалось отключить NuGet-источник: {e}", tag="warn")
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

    # ================== Очистка и пересборка ==================

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

    # ================== Переустановка, удаление, обновление ==================

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

    def delete_build(self):
        name = self._get_selected_name()
        if not name:
            return
        if self._is_game_running(name):
            self._stop_game(name)
            time.sleep(0.5)

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
                    self.notify_tray("Удалено", f"Сборка '{name}' удалена.")
                    self.show_notification("Готово", f"Сборка '{name}' удалена.")
            finally:
                self.after(0, lambda: self._end_operation(name))

        threading.Thread(target=_del, daemon=True).start()

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

    # ================== Загрузка готовой сборки ==================

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
                self._download_cancel_event.clear()
                zip_path = self.download_manager.download(
                    url, dest_name=f"{name}.zip",
                    progress_callback=self._download_progress,
                    cancel_event=self._download_cancel_event
                )
                if not zip_path:
                    raise Exception("Не удалось скачать архив")
                self.log("✅ Загрузка завершена. Распаковка...", tag="success")
                dest_dir = os.path.join(self.builds_dir, name)
                dest_real = os.path.realpath(dest_dir)
                os.makedirs(dest_dir, exist_ok=True)

                with zipfile.ZipFile(zip_path, 'r') as zf:
                    for member in zf.infolist():
                        member_path = os.path.realpath(os.path.join(dest_dir, member.filename))
                        if not member_path.startswith(dest_real + os.sep):
                            raise Exception(f"Опасный путь в архиве: {member.filename}")
                    zf.extractall(dest_dir)
                os.remove(zip_path)
                self.log("✅ Готовая сборка установлена.", tag="success")
            except Exception as e:
                self.log(f"❌ Ошибка: {e}", tag="error")
            finally:
                if self._cancel_download and zip_path and os.path.exists(zip_path):
                    os.remove(zip_path)
                self.after(0, lambda: self._end_operation(name))

        threading.Thread(target=_download, daemon=True).start()

    # ================== Вспомогательные методы для git и файлов ==================

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
                                   capture_output=True, timeout=10,
                                   startupinfo=self._hidden_startupinfo(),
                                   creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
                else:
                    shutil.rmtree(cache_dir, ignore_errors=True)
            # Мгновенное перемещение .git в кэш
            shutil.move(str(git_dir), str(cache_dir))
            self.log(f"💾 Git-кэш для '{name}' перемещён.", tag="info")
        except Exception as e:
            self.log(f"⚠ Не удалось переместить git-кэш: {e}", tag="warn")

    def _log_clone_failure_help(self):
        self.log("❌ Клонирование не удалось.", tag="error")
        self.log("Возможные причины:", tag="warn")
        self.log("  - Нестабильное интернет-соединение или обрыв связи.", tag="info")
        self.log("  - Слишком большой объём данных (уменьшите через shallow clone).", tag="info")
        self.log("  - Временные проблемы на сервере GitHub.", tag="info")
        self.log("Рекомендации:", tag="bold")
        self.log("  1. Проверьте подключение к интернету.", tag="info")
        self.log("  2. Включите опцию 'Shallow clone' в настройках (уменьшает размер).", tag="info")
        self.log("  3. Попробуйте повторить установку позже.", tag="info")
        self.log("  4. Если проблема повторяется, используйте VPN или смените сеть.", tag="info")

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

    # ================== Подготовка и команды сборки ==================

    def _run_pre_restore_if_needed(self, build_path):
        if self.settings.get("pre_restore", False):
            self.log("Выполняется предварительное восстановление пакетов (dotnet restore)...", tag="info")
            if not self._run_subprocess(["dotnet", "restore"], build_path, "dotnet restore"):
                self.log("⚠ Ошибка восстановления пакетов.", tag="warn")

    def _get_build_command(self, mode="Debug"):
        cmd = ["dotnet", "build"]
        if self.settings.get("parallel_build", False):
            cmd.append("-m")
        if mode == "Release":
            cmd += ["-c", "Release"]
        return cmd

    def _prompt_install_missing_sdk(self, required_version, build_name, build_path):
        if messagebox.askyesno("Установка .NET SDK",
                               f"Программа может автоматически скачать и запустить установщик .NET SDK {required_version}.\n\n"
                               "Продолжить?"):
            self._download_and_install_sdk(required_version, build_name, build_path)
        else:
            self.after(0, lambda: self._end_operation(build_name))
            self.after(0, self._install_failed, build_name, build_path)

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