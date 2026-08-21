# core/config.py
import json
import shutil
from pathlib import Path

CONFIG_VERSION = 60


class ConfigManager:
    def __init__(self, config_file=None):
        if config_file is None:
            from utils.system import get_data_dir
            config_file = get_data_dir() / "config.json"
        self.config_file = Path(config_file)
        self.data = self.load()

    def default_repositories(self):
        return {
            "Spelward": {
                "url": "https://github.com/imperial-space/SW-public.git",
                "mode": "Debug",
                "prebuilt_url": None,
                "favorite": False
            },
            "Мёртвый Космос": {
                "url": "https://github.com/dead-space-server/space-station-14-fobos.git",
                "mode": "Debug",
                "prebuilt_url": "https://cdn.deadspace14.net/fork/dspublicfobos",
                "favorite": False
            },
            "Imperial Space": {
                "url": "https://github.com/imperial-space/SS14-public.git",
                "mode": "Debug",
                "favorite": False
            },
            "Wizards": {
                "url": "https://github.com/space-wizards/space-station-14.git",
                "mode": "Debug",
                "favorite": False
            },
            "Corvax": {
                "url": "https://github.com/space-syndicate/space-station-14.git",
                "mode": "Debug",
                "favorite": False
            },
            "CorvaxGoob": {
                "url": "https://github.com/space-syndicate/Goob-Station.git",
                "mode": "Debug",
                "favorite": False
            },
            "Space Stories": {
                "url": "https://github.com/MetalSage/space-stories-14.git",
                "mode": "Debug",
                "favorite": False
            }
        }

    def default_settings(self):
        return {
            "console_font_family": "Consolas",
            "console_font_size": 10,
            "console_line_spacing": 2,
            "console_bg": "#000000",
            "console_fg": "#33ff33",
            "console_buffer_size": 10000,
            "check_updates": True,
            "console_colors": {
                "error": "#ff5555",
                "success": "#00ff88",
                "warn": "#ffaa00",
                "info": "#32CD32",
                "bold": "#ffffff",
                "operation": "#66ccff",
                "done": "#00ffaa",
                "cancel": "#cc66cc",
                "server": "#ffaa00",
                "server_warn": "#ff6600",
                "server_error": "#ff2200",
                "client": "#00ccff",
                "client_warn": "#00ffcc",
                "client_error": "#ff00aa",
                }
        }

    def default_log_filters(self):
        return {"client": True, "server": True, "manager": True}

    def load(self):
        defaults = {
            "config_version": CONFIG_VERSION,
            "repositories": self.default_repositories(),
            "log_filters": self.default_log_filters(),
            "settings": self.default_settings()
        }

        if self.config_file.exists():
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                # Миграция репозиториев: добавляем недостающие поля внутри каждого репозитория,
                # сохраняем пользовательские репозитории без восстановления удалённых.
                if "repositories" in data:
                    migrated_repos = {}
                    for name, val in data["repositories"].items():
                        if isinstance(val, str):
                            migrated_repos[name] = {"url": val, "mode": "Debug", "favorite": False}
                        elif isinstance(val, dict):
                            migrated_repos[name] = {
                                "url": val.get("url", ""),
                                "mode": val.get("mode", "Debug"),
                                "prebuilt_url": val.get("prebuilt_url"),
                                "favorite": val.get("favorite", False)
                            }
                        else:
                            migrated_repos[name] = val
                    data["repositories"] = migrated_repos

                def deep_merge(default, user):
                    result = default.copy()
                    for key, value in user.items():
                        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                            result[key] = deep_merge(result[key], value)
                        else:
                            result[key] = value
                    return result

                merged = defaults.copy()
                if "settings" in data:
                    merged["settings"] = deep_merge(defaults["settings"], data["settings"])
                if "log_filters" in data:
                    merged["log_filters"] = deep_merge(defaults["log_filters"], data["log_filters"])
                if "repositories" in data:
                    merged["repositories"] = data["repositories"]

                merged["config_version"] = CONFIG_VERSION
                self.data = merged
            except Exception:
                self.data = defaults
        else:
            self.data = defaults
        return self.data

    def save(self):
        # Резервная копия
        backup = self.config_file.with_suffix(".json.bak")
        if self.config_file.exists():
            shutil.copy2(self.config_file, backup)

        with open(self.config_file, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=4, ensure_ascii=False)

    def restore_from_backup(self):
        backup = self.config_file.with_suffix(".json.bak")
        if backup.exists():
            shutil.copy2(backup, self.config_file)
            self.data = self.load()
            return True
        return False