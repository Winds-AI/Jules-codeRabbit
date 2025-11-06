"""Application configuration helpers."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import AnyHttpUrl, BaseModel, ValidationError

# Load environment variables from .env file
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(dotenv_path=env_path)


class SettingsError(RuntimeError):
    """Raised when application configuration is invalid or incomplete."""


class Settings(BaseModel):
    """Runtime settings loaded from environment variables."""

    service_base_url: AnyHttpUrl
    manifest_public: bool = False
    github_api_base_url: AnyHttpUrl = "https://api.github.com"

    @property
    def normalized_base_url(self) -> str:
        """Return the base service URL without a trailing slash."""
        return str(self.service_base_url).rstrip("/")

    @property
    def normalized_github_api_base_url(self) -> str:
        """Return the GitHub API base URL without a trailing slash."""
        return str(self.github_api_base_url).rstrip("/")


def _build_settings() -> Settings:
    service_base_url = os.getenv("SERVICE_BASE_URL")
    if not service_base_url:
        raise SettingsError("SERVICE_BASE_URL environment variable is required.")

    manifest_public = os.getenv("MANIFEST_PUBLIC", False)

    github_api_base_url = os.getenv("GITHUB_API_BASE_URL")

    try:
        return Settings(
            service_base_url=service_base_url,
            manifest_public=manifest_public,
            github_api_base_url=github_api_base_url or "https://api.github.com",
        )
    except ValidationError as exc:
        raise SettingsError("Invalid application configuration.") from exc


@lru_cache(maxsize=1)
def _cached_settings() -> Settings:
    return _build_settings()


def get_settings() -> Settings:
    """Retrieve cached application settings."""
    return _cached_settings()


def reset_settings_cache() -> None:
    """Clear the cached settings (primarily for tests)."""
    _cached_settings.cache_clear()
