"""Shared utilities for webhook server."""

import sys
import os


def log_info(message: str) -> None:
    """Print info message."""
    print(f"[INFO] {message}", file=sys.stdout, flush=True)


def log_error(message: str) -> None:
    """Print error message."""
    print(f"[ERROR] {message}", file=sys.stderr, flush=True)


def log_debug(message: str) -> None:
    """Print debug message if DEBUG enabled."""
    if os.getenv("DEBUG"):
        print(f"[DEBUG] {message}", file=sys.stdout, flush=True)
