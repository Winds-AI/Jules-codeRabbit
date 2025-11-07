"""Application configuration helpers."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Final

from dotenv import load_dotenv
from pydantic import AnyHttpUrl, BaseModel, ValidationError

# Load environment variables from .env file
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(dotenv_path=env_path)


class SettingsError(RuntimeError):
    """Raised when application configuration is invalid or incomplete."""


@dataclass(frozen=True)
class CodeReviewCredentials:
    github_app_id: int
    github_private_key_pem: str
    github_webhook_secret: str
    jules_api_key: str


class Settings(BaseModel):
    """Runtime settings loaded from environment variables."""

    service_base_url: AnyHttpUrl
    manifest_public: bool = False
    github_api_base_url: AnyHttpUrl = "https://api.github.com"
    github_app_id: int | None = None
    github_private_key_pem: str | None = None
    github_webhook_secret: str | None = None
    jules_api_key: str | None = None

    @property
    def normalized_base_url(self) -> str:
        """Return the base service URL without a trailing slash."""
        return str(self.service_base_url).rstrip("/")

    @property
    def normalized_github_api_base_url(self) -> str:
        """Return the GitHub API base URL without a trailing slash."""
        return str(self.github_api_base_url).rstrip("/")

    def require_code_review_credentials(self) -> CodeReviewCredentials:
        """Ensure code-review secrets are configured and return them."""

        missing = []
        if self.github_app_id is None:
            missing.append("GITHUB_APP_ID")
        if not self.github_private_key_pem:
            missing.append("GITHUB_PRIVATE_KEY")
        if not self.github_webhook_secret:
            missing.append("GITHUB_WEBHOOK_SECRET")
        if not self.jules_api_key:
            missing.append("JULES_API_KEY")

        if missing:
            missing_vars = ", ".join(missing)
            raise SettingsError(
                "Code review is not configured. Missing environment variables: "
                f"{missing_vars}."
            )

        return CodeReviewCredentials(
            github_app_id=int(self.github_app_id),
            github_private_key_pem=self.github_private_key_pem,
            github_webhook_secret=self.github_webhook_secret,
            jules_api_key=self.jules_api_key,
        )


_TRUE_VALUES: Final[set[str]] = {"1", "true", "yes", "on"}


def _parse_bool_env(raw_value: str | None, *, default: bool = False) -> bool:
    """Convert an environment variable string to a boolean value."""

    if raw_value is None:
        return default
    return raw_value.strip().lower() in _TRUE_VALUES


def _build_settings() -> Settings:
    service_base_url = os.getenv("SERVICE_BASE_URL")
    if not service_base_url:
        raise SettingsError("SERVICE_BASE_URL environment variable is required.")

    manifest_public = _parse_bool_env(os.getenv("MANIFEST_PUBLIC"), default=False)

    github_api_base_url = os.getenv("GITHUB_API_BASE_URL")
    github_app_id = os.getenv("GITHUB_APP_ID")
    github_private_key_pem = os.getenv("GITHUB_PRIVATE_KEY")
    github_webhook_secret = os.getenv("GITHUB_WEBHOOK_SECRET")
    jules_api_key = os.getenv("JULES_API_KEY")

    try:
        github_app_id_value: int | None
        if github_app_id and github_app_id.strip():
            github_app_id_value = int(github_app_id)
        else:
            github_app_id_value = None

        return Settings(
            service_base_url=service_base_url,
            manifest_public=manifest_public,
            github_api_base_url=github_api_base_url or "https://api.github.com",
            github_app_id=github_app_id_value,
            github_private_key_pem=github_private_key_pem,
            github_webhook_secret=github_webhook_secret,
            jules_api_key=jules_api_key,
        )
    except ValueError as exc:
        raise SettingsError("Invalid value for GITHUB_APP_ID. It must be an integer.") from exc
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
