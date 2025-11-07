"""FastAPI dependency factories."""

from __future__ import annotations

from functools import lru_cache

from fastapi import HTTPException

from src.config import Settings, SettingsError, get_settings
from src.github_client import GitHubAppClient
from src.logger import get_logger

logger = get_logger()


def settings_dependency() -> Settings:
    """Resolve application settings, surfacing configuration errors via HTTPException."""

    try:
        return get_settings()
    except SettingsError as exc:
        logger.error(f"Failed to load settings: {exc}")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@lru_cache(maxsize=1)
def _github_client_factory(base_url: str) -> GitHubAppClient:
    return GitHubAppClient(base_url=base_url)


def github_client_dependency() -> GitHubAppClient:
    """Provide a cached GitHub client instance."""

    settings = settings_dependency()
    return _github_client_factory(settings.normalized_github_api_base_url)


def reset_github_client_cache() -> None:
    """Clear the cached GitHub client instance (primarily for tests)."""

    _github_client_factory.cache_clear()
