# python_back_end/research/config/logging.py
import logging
import os
from logging.config import dictConfig

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_JSON = os.getenv("LOG_JSON", "0") in ("1", "true", "True")

def _json_formatter():
    # minimal JSON formatter without extra deps
    class JsonFormatter(logging.Formatter):
        def format(self, record: logging.LogRecord) -> str:
            import json, time
            payload = {
                "ts": int(time.time() * 1000),
                "level": record.levelname,
                "name": record.name,
                "msg": record.getMessage(),
            }
            if record.exc_info:
                payload["exc_info"] = self.formatException(record.exc_info)
            return json.dumps(payload, ensure_ascii=False)
    return JsonFormatter()

def configure_logging() -> None:
    """
    Configure root logging. Call once at app start.
    Uses JSON if LOG_JSON=1, otherwise pretty console.
    """
    if LOG_JSON:
        dictConfig({
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "json": {
                    "()": "research.config.logging._json_formatter"
                }
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "json",
                    "level": LOG_LEVEL
                }
            },
            "root": {"level": LOG_LEVEL, "handlers": ["console"]},
        })
    else:
        dictConfig({
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "console": {
                    "format": "[%(asctime)s] %(levelname)s %(name)s: %(message)s",
                    "datefmt": "%H:%M:%S"
                }
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "console",
                    "level": LOG_LEVEL
                }
            },
            "root": {"level": LOG_LEVEL, "handlers": ["console"]},
        })

def get_logger(name: str) -> logging.Logger:
    """
    Convenience accessor—ensures configure_logging called once.
    """
    if not logging.getLogger().handlers:
        configure_logging()
    return logging.getLogger(name)

