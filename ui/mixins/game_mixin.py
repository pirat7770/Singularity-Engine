# ui/mixins/game_mixin.py
import os
import time
import threading
import subprocess
from pathlib import Path
from collections import deque
import re
from tkinter import messagebox
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    psutil = None
    PSUTIL_AVAILABLE = False

from utils.system import open_path as sys_open_path


class GameMixin:
    """Методы управления запущенными экземплярами игры."""

    # ================== Порты ==================

    def _is_port_in_use(self, port):
        return self.port_allocator.is_port_in_use(port)

    def _allocate_port(self, start=1212, limit=200):
        return self.port_allocator.allocate()

    def _release_port(self, port):
        self.port_allocator.release(port)

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

        # Fallback через netstat и tasklist
        try:
            output = subprocess.run(["netstat", "-ano", "-p", "udp"], capture_output=True, text=True,
                                    startupinfo=self._hidden_startupinfo()).stdout
            for line in output.splitlines():
                if f":{port}" in line:
                    parts = line.split()
                    if not parts or not parts[-1].isdigit():
                        continue
                    pid = int(parts[-1])
                    tasklist = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"],
                                              capture_output=True, text=True,
                                              startupinfo=self._hidden_startupinfo()).stdout
                    process_name = ""
                    for tl_line in tasklist.splitlines()[1:]:
                        if str(pid) in tl_line:
                            process_name = tl_line.split()[0].lower()
                            break
                    if process_name and any(kw in process_name for kw in allowed_kw):
                        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True,
                                       startupinfo=self._hidden_startupinfo())
                        self.log(f"🛑 Завершён процесс (PID {pid}) с портом {port}", tag="warn")
                        return True
                    else:
                        self.log(f"⚠ Порт {port} занят процессом PID {pid} (не игровой). Не буду убивать.",
                                 tag="warn")
                        return False
        except Exception as e:
            self.log(f"⚠ Не удалось освободить порт {port}: {e}", tag="warn")
        return False

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

    # ================== Запуск/остановка игры ==================

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
            self.notify_tray("Остановлено", f"Все экземпляры '{name}' остановлены.")
            self.show_notification("Остановлено", f"Все экземпляры '{name}' остановлены.")
            self._end_operation(name)

        threading.Thread(target=_stop, daemon=True).start()

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
                except Exception as e:
                    self.log(f"⚠ Ошибка при остановке процесса: {e}", tag="warn")
                    try:
                        p.kill()
                    except Exception as e2:
                        self.log(f"⚠ Ошибка при принудительном завершении процесса: {e2}", tag="warn")

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

    def _check_game_processes(self, instance_id):
        if instance_id not in self._instances:
            return
        inst = self._instances[instance_id]
        srv_alive = inst["srv"] is not None and inst["srv"].poll() is None
        cli_alive = inst["cli"] is not None and inst["cli"].poll() is None

        if not srv_alive and not cli_alive:
            if inst.get("owns_port"):
                self._release_port(inst.get("port"))
            inst["finished"] = True
            self._refresh_instance_list()
            self.refresh_builds_list()
            self.on_build_select(None)
            self._refresh_console_view()
            return
        else:
            self.after(2000, lambda: self._check_game_processes(instance_id))

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
        except Exception as e:
            self.log(f"⚠ Ошибка чтения вывода процесса: {e}", tag="warn")
        finally:
            if process.poll() is None:
                process.terminate()

    # ================== Обновление списка экземпляров ==================

    def _auto_refresh_instances(self):
        if not self._closing:
            self._refresh_instance_list()
            self.after(2000, self._auto_refresh_instances)

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

    # ================== Обработчики GUI списка экземпляров ==================

    def _on_instance_select(self, event, instance_id=None):
        if instance_id is None:
            selection = self.instance_tree.selection()
            if selection:
                instance_id = selection[0]
                self._current_instance_id = instance_id
                self._refresh_console_view()
            else:
                self._current_instance_id = None
                self._refresh_console_view()
        else:
            self._current_instance_id = instance_id
            self._refresh_console_view()

    def _on_instance_click(self, event):
        region = self.instance_tree.identify("region", event.x, event.y)
        column = self.instance_tree.identify_column(event.x)
        item = self.instance_tree.identify("item", event.x, event.y)
        if region == "cell" and column == "#4" and item:
            self._stop_instance(item)

    def _stop_selected_instance(self):
        selection = self.instance_tree.selection()
        if selection:
            self._stop_instance(selection[0])

    def _show_system_logs(self):
        self._current_instance_id = None
        self._rebuild_console()
        self._refresh_instance_list()

    def stop_selected_build(self):
        name = self._get_selected_name()
        if name and self._is_game_running(name):
            self._stop_game(name)

    # ================== Открытие папок ==================

    def open_logs_folder(self):
        log_dir = self.data_dir / "logs"
        log_dir.mkdir(exist_ok=True)
        sys_open_path(log_dir)

    def open_upload_folder(self):
        upload_path = Path(os.environ.get("APPDATA", "")) / "Space Station 14" / "data" / "UploadFolder"
        if upload_path.exists():
            sys_open_path(upload_path)
        else:
            messagebox.showinfo("Папка не найдена", f"UploadFolder не существует:\n{upload_path}")

    def open_build_folder(self):
        name = self._get_selected_name()
        if name:
            build_path = os.path.join(self.builds_dir, name)
            sys_open_path(build_path)

    def open_builds_folder(self):
        if self.builds_dir.exists():
            sys_open_path(self.builds_dir)
        else:
            messagebox.showinfo("Папка не найдена", f"Папка сборок не существует:\n{self.builds_dir}")

    # ================== Вспомогательные методы ==================

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
