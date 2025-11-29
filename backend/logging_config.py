import logging
import logging.config
import os

BASE_DIR = os.path.dirname(__file__)
LOG_DIR = os.path.join(BASE_DIR, "logs")

# Three separate log files
APP_LOG_FILE = os.path.join(LOG_DIR, "privas_app.log")
ACCESS_LOG_FILE = os.path.join(LOG_DIR, "privas_access.log")
ERROR_LOG_FILE = os.path.join(LOG_DIR, "privas_error.log")

LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "format": "[%(asctime)s] [%(levelname)s] %(name)s - %(message)s"
        },
        "verbose": {
            "format": "[%(asctime)s] [%(levelname)s] [%(name)s:%(lineno)d] - %(message)s"
        },
        "access": {
            "format": "[%(asctime)s] [ACCESS] %(message)s"
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "default",
            "level": "INFO",
            "stream": "ext://sys.stdout",
        },
        "app_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "formatter": "verbose",
            "level": "INFO",
            "filename": APP_LOG_FILE,
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 5,
            "encoding": "utf-8",
        },
        "access_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "formatter": "access",
            "level": "INFO",
            "filename": ACCESS_LOG_FILE,
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 5,
            "encoding": "utf-8",
        },
        "error_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "formatter": "verbose",
            "level": "WARNING",
            "filename": ERROR_LOG_FILE,
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 5,
            "encoding": "utf-8",
        },
    },
    "loggers": {
        "uvicorn": {"handlers": ["console", "error_file"], "level": "INFO", "propagate": False},
        "uvicorn.error": {"handlers": ["console", "error_file"], "level": "INFO", "propagate": False},
        "uvicorn.access": {"handlers": ["console", "access_file"], "level": "INFO", "propagate": False},
        "privas.app": {"handlers": ["console", "app_file"], "level": "INFO", "propagate": False},
    },
    "root": {"level": "INFO", "handlers": ["console", "app_file"]},
}


def init_logging():
    """Ensure logs directory exists and apply logging configuration."""
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
    except Exception:
        # best-effort: if directory creation fails, continue and let handlers fail later
        pass

    # Apply configuration
    logging.config.dictConfig(LOGGING_CONFIG)


__all__ = ["init_logging", "LOGGING_CONFIG"]
