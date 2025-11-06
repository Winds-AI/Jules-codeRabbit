"""FastAPI dependency factories."""

from __future__ import annotations
from src.logger import logger

from fastapi import HTTPException

from src.config import Settings, SettingsError, get_settings


def settings_dependency() -> Settings:
    """Resolve application settings, surfacing configuration errors via HTTPException."""
    try:
        return get_settings()
    except SettingsError as exc:
        logger.error(f"Failed to load settings: {exc}")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
