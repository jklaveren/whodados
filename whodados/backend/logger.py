"""Logger estruturado para o WhoDados."""
import logging
import sys
from typing import Any, Dict

try:
    from .config import settings
except ImportError:
    import os
    class _Settings:
        LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
        LOG_FORMAT = os.getenv("LOG_FORMAT", "text")
        is_production = os.getenv("APP_ENV", "development") == "production"
    settings = _Settings()

class TextFormatter(logging.Formatter):
    COLORS = {
        "DEBUG": "\x1b[38;5;244m",
        "INFO": "\x1b[38;5;39m",
        "WARNING": "\x1b[38;5;214m",
        "ERROR": "\x1b[38;5;196m",
        "CRITICAL": "\x1b[38;5;201m",
    }
    RESET = "\x1b[0m"

    def format(self, record):
        color = self.COLORS.get(record.levelname, "")
        ts = self.formatTime(record, "%Y-%m-%d %H:%M:%S")
        return f"{color}[{record.levelname}]{self.RESET} {ts} {record.name}:{record.lineno} — {record.getMessage()}"

def configure_logging():
    root = logging.getLogger()
    root.setLevel(getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))
    for handler in root.handlers[:]:
        root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(TextFormatter())
    root.addHandler(handler)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

def get_logger(name):
    return logging.getLogger(name)

configure_logging()
logger = get_logger("whodados")