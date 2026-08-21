# main.py
import sys
import os
import traceback
import ctypes
import subprocess
from ui.main_window import SingularityEngineApp

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

def run_as_admin():
    """Перезапускает программу с правами администратора (корректно обрабатывая пробелы в путях)."""
    try:
        # Используем subprocess для корректной передачи аргументов
        params = ' '.join([f'"{arg}"' for arg in sys.argv])
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, params, None, 1
        )
        return True
    except Exception as e:
        print(f"Не удалось запустить от имени администратора: {e}")
        return False

def main():
    try:
        app = SingularityEngineApp()
        app.mainloop()
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as e:
        # Выводим traceback в консоль
        traceback.print_exc()
        # И записываем в файл
        with open("error.log", "w", encoding="utf-8") as f:
            traceback.print_exc(file=f)
        input("Произошла ошибка. Подробности в error.log. Нажмите Enter для выхода...")
        sys.exit(1)

if __name__ == "__main__":
    main()