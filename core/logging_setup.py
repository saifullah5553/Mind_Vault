"""Centralized logging for Mind_Vault.

DESIGN: One `configure_logging()` call wires up (a) a console handler and (b) a
rotating file handler writing to `logs/mind_vault.log`. Every agent gets a child
logger via `get_logger("agent.trend")`, so logs are namespaced and filterable.
Optional JSON formatting (config.logging.json) makes logs shippable to a log
aggregator later without code changes.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
from pathlib import Path

from core.config import ROOT_DIR, get_settings

_CONFIGURED = False


class _JsonFormatter(logging.Formatter):
    """Minimal structured formatter — no external deps."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # Attach any structured extras the caller passed via `extra={...}`.
        for key in ("agent", "run_id", "stage", "duration_ms", "event"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(force: bool = False) -> None:
    """Idempotently configure the root logger from settings."""
    global _CONFIGURED
    if _CONFIGURED and not force:
        return

    cfg = get_settings().logging
    log_dir = ROOT_DIR / cfg.dir
    log_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(cfg.level.upper())
    # Clear existing handlers so re-configuration (tests) is clean.
    for h in list(root.handlers):
        root.removeHandler(h)

    if cfg.json_logs:
        formatter: logging.Formatter = _JsonFormatter()
    else:
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-7s | %(name)-24s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / "mind_vault.log",
        maxBytes=cfg.rotate_mb * 1024 * 1024,
        backupCount=cfg.backups,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    # Quiet noisy third-party libraries.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced logger, configuring logging on first use."""
    configure_logging()
    return logging.getLogger(f"mind_vault.{name}")
