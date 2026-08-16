import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from utils.system import get_data_dir

LOG_DIR = get_data_dir() / "logs"
LOG_DIR.mkdir(exist_ok=True)


def setup_logger():
    logger = logging.getLogger("SS14Manager")
    logger.setLevel(logging.DEBUG)

    file_handler = RotatingFileHandler(
        LOG_DIR / "manager.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    file_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    return logger


logger = setup_logger()