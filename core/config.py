import json
import shutil
from pathlib import Path

CONFIG_VERSION = 56


class ConfigManager:
    def __init__(self, config_file="config.json"):
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
            "auto_delete_failed": False,
            "confirm_clean_rebuild": False,
            "theme": "Стандартная",
            "shallow_clone": False,
            "parallel_build": False,
            "pre_restore": False,
            "strict_sdk_major": True,
            "auto_install_deps": False,
            "confirm_destructive": True,
            "keep_finished_instances": True,
            "enable_git_cache": True,
            "minimize_to_tray": False,
            "max_instances": 5,
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

                # Миграция старых конфигов
                if "repositories" in data:
                    repos = data["repositories"]
                    migrated = {}
                    for name, val in repos.items():
                        if isinstance(val, str):
                            migrated[name] = {
                                "url": val,
                                "mode": "Debug",
                                "favorite": False
                            }
                        elif isinstance(val, dict) and "url" in val:
                            migrated[name] = {
                                "url": val["url"],
                                "mode": val.get("mode", "Debug"),
                                "prebuilt_url": val.get("prebuilt_url"),
                                "favorite": val.get("favorite", False)
                            }
                        else:
                            migrated[name] = val
                    data["repositories"] = migrated

                defaults.update(data)
            except Exception:
                pass

        return defaults

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