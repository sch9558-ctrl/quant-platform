"""Shared logging setup."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from quant import config

_CONFIGURED = False


def get_logger(name: str) -> logging.Logger:
    global _CONFIGURED
    logger = logging.getLogger(name)
    if not _CONFIGURED:
        _configure_root()
        _CONFIGURED = True
    return logger


def _configure_root() -> None:
    try:
        s = config.settings()
        level = getattr(logging, s.get("logging", {}).get("level", "INFO"))
        log_file = config.resolve_path(s.get("logging", {}).get("file", "logs/quant.log"))
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        handlers = [logging.StreamHandler(sys.stdout), logging.FileHandler(log_file, encoding="utf-8")]
    except Exception:
        level = logging.INFO
        handlers = [logging.StreamHandler(sys.stdout)]

    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        handlers=handlers,
        force=True,
    )
