from __future__ import annotations

import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from loguru import logger as _logger

_CONFIGURED = False
DEFAULT_LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_DIR_ENV = "APP_LOG_DIR"


def _resolve_log_dir(explicit: str | Path | None) -> Path:
    """Determine the directory to store log files."""

    if explicit is not None:
        return Path(explicit).expanduser().resolve()
    env_value = os.getenv(LOG_DIR_ENV)
    if env_value:
        return Path(env_value).expanduser().resolve()
    return DEFAULT_LOG_DIR


def configure_logger(*, log_dir: str | Path | None = None, level: str | None = None) -> None:
    """Configure the Loguru logger exactly once per process."""

    global _CONFIGURED
    if _CONFIGURED:
        return

    target_dir = _resolve_log_dir(log_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    log_level = level or os.getenv("APP_LOG_LEVEL", "INFO")

    _logger.remove()
    log_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
    )

    _logger.add(
        sys.stdout,
        level=log_level,
        format=log_format,
        colorize=sys.stdout.isatty(),
    )
    _logger.add(
        target_dir / "{time:YYYY-MM-DD}.log",
        rotation="50 MB",
        retention="10 days",
        level="DEBUG",
        format=log_format,
        enqueue=True,
        backtrace=True,
        diagnose=True,
    )

    _CONFIGURED = True


def get_logger(*, log_dir: str | Path | None = None, level: str | None = None):
    """Return the configured logger, configuring it on first access."""

    configure_logger(log_dir=log_dir, level=level)
    return _logger


def log_with_context(logger_instance, **context: str | int | None) -> Any:
    """Add context fields to log messages.
    
    Usage:
        logger = log_with_context(get_logger(), delivery_id="123", repository="owner/repo")
        logger.info("Processing job")
    """
    return logger_instance.bind(**{k: v for k, v in context.items() if v is not None})


def log_timing(logger_instance, operation: str, **context: str | int | None):
    """Context manager to log operation timing.
    
    Usage:
        with log_timing(logger, "fetch_files", repository="owner/repo"):
            # operation code
    """
    @contextmanager
    def _timing():
        start_time = time.time()
        ctx_logger = log_with_context(logger_instance, **context)
        ctx_logger.debug(f"Starting {operation}")
        try:
            yield ctx_logger
            duration = time.time() - start_time
            ctx_logger.debug(f"Completed {operation} in {duration:.3f}s")
        except Exception as exc:
            duration = time.time() - start_time
            ctx_logger.error(f"Failed {operation} after {duration:.3f}s: {exc}")
            raise
    return _timing()


def log_success(logger_instance, message: str, **context: str | int | None) -> None:
    """Log a success message with context."""
    log_with_context(logger_instance, **context).info(f"=== SUCCESS: {message} ===")


def log_failure(logger_instance, message: str, error: Exception | None = None, **context: str | int | None) -> None:
    """Log a failure message with context and optional error."""
    ctx_logger = log_with_context(logger_instance, **context)
    if error:
        ctx_logger.error(f"=== FAILURE: {message} | Error: {error} ===")
    else:
        ctx_logger.error(f"=== FAILURE: {message} ===")
