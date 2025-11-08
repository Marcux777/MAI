from __future__ import annotations

import logging
from logging.config import dictConfig


def configure_logging(debug: bool = False) -> None:
    level = "DEBUG" if debug else "INFO"
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "structured": {
                    "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
                }
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "structured",
                    "level": level,
                }
            },
            "root": {"handlers": ["console"], "level": level},
        }
    )


logger = logging.getLogger("mai")
