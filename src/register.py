from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from src.config import Settings
from src.dependencies import settings_dependency
from src.github_client import GitHubAPIError, GitHubAppClient

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))

router = APIRouter()


REQUIRED_CONVERSION_KEYS = {
    "id",
    "slug",
    "client_id",
    "client_secret",
    "webhook_secret",
}


def _quote_env_value(value: Any) -> str:
    """Return a safely quoted environment variable value."""

    if value is None:
        raw_text = ""
    else:
        raw_text = str(value)

    escaped_text = (
        raw_text.replace("\\", "\\\\")
        .replace("\"", "\\\"")
        .replace("$", "\\$")
        .replace("\n", "\\n")
    )
    return f'"{escaped_text}"'


def _validate_conversion_payload(conversion: Dict[str, Any]) -> None:
    """Ensure the conversion payload contains all required credentials."""

    missing = sorted(key for key in REQUIRED_CONVERSION_KEYS if not conversion.get(key))
    if missing:
        missing_list = ", ".join(missing)
        raise ValueError(
            "Incomplete GitHub App manifest conversion payload. Missing fields: "
            f"{missing_list}"
        )


def github_client_dependency(
    settings: Settings = Depends(settings_dependency),
) -> GitHubAppClient:
    """Instantiate a GitHub App client for API interactions."""
    return GitHubAppClient(base_url=settings.normalized_github_api_base_url)


def _normalize_env_vars(conversion: Dict[str, Any], base_url: str) -> Dict[str, str]:
    env_vars = {
        "GITHUB_APP_ID": conversion.get("id", ""),
        "GITHUB_APP_SLUG": conversion.get("slug", ""),
        "GITHUB_CLIENT_ID": conversion.get("client_id", ""),
        "GITHUB_CLIENT_SECRET": conversion.get("client_secret", ""),
        "GITHUB_WEBHOOK_SECRET": conversion.get("webhook_secret", ""),
        "GITHUB_PRIVATE_KEY": "<paste PEM contents>",
        "SERVICE_BASE_URL": base_url,
    }
    return {key: _quote_env_value(value) for key, value in env_vars.items()}


def _build_summary(conversion: Dict[str, Any]) -> List[Tuple[str, Optional[str]]]:
    return [
        ("App ID", conversion.get("id")),
        ("Slug", conversion.get("slug")),
        ("Client ID", conversion.get("client_id")),
        ("Client Secret", conversion.get("client_secret")),
        ("Webhook Secret", conversion.get("webhook_secret")),
    ]


def _build_pem_artifacts(conversion: Dict[str, Any]) -> Optional[Dict[str, str]]:
    pem_value = conversion.get("pem") or ""
    if not pem_value:
        return None

    pem_bytes = pem_value.encode("utf-8")
    pem_download_href = "data:application/x-pem-file;base64," + base64.b64encode(pem_bytes).decode(
        "ascii"
    )
    slug_value = str(conversion.get("slug") or "github-app").strip().replace(" ", "-") or "github-app"
    pem_filename = f"{slug_value}-private-key.pem"
    return {"href": pem_download_href, "filename": pem_filename}


def _mock_conversion_payload(base_url: str) -> Dict[str, Any]:
    return {
        "id": "123456",
        "slug": "jules-code-reviewer",
        "client_id": "Iv1.0123456789abcdef",
        "client_secret": "mock_client_secret_ABC123",
        "webhook_secret": "mock_webhook_secret_DEF456",
        "pem": """-----BEGIN PRIVATE KEY-----\nMIIBVwIBADANBgkqhkiG9w0BAQEFAASCAT8wggE7AgEAAkEAuMockKeyPreview\n-----END PRIVATE KEY-----\n""",
        "mock_base_url": base_url,
    }


@router.get(
    "/register",
    summary="Handle GitHub App manifest conversion callback",
    response_class=HTMLResponse,
)
async def register_app(
    request: Request,
    code: str | None = Query(
        None,
        description="Temporary manifest code provided by GitHub.",
    ),
    preview: bool = Query(
        False,
        description="Render the success page with mock data for visual preview.",
    ),
    settings: Settings = Depends(settings_dependency),
    github_client: GitHubAppClient = Depends(github_client_dependency),
) -> HTMLResponse:
    """Exchange the manifest code for GitHub App credentials and present them to the user."""

    base_url = settings.normalized_base_url
    if preview:
        conversion = _mock_conversion_payload(base_url)
    else:
        if not code:
            raise HTTPException(
                status_code=400,
                detail="GitHub manifest code is required unless preview mode is enabled.",
            )

        try:
            conversion = await github_client.convert_manifest(code)
        except GitHubAPIError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to convert GitHub App manifest: {exc}",
            ) from exc

        try:
            _validate_conversion_payload(conversion)
        except ValueError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    pem_artifacts = _build_pem_artifacts(conversion)
    env_vars = _normalize_env_vars(conversion, base_url)
    env_lines = [f"{key}={value}" for key, value in env_vars.items()]

    context = {
        "request": request,
        "base_url": base_url,
        "summary": _build_summary(conversion),
        "raw_conversion": json.dumps(conversion, indent=2),
        "env_values": env_vars,
        "env_lines": env_lines,
        "pem_artifacts": pem_artifacts,
        "preview": preview,
    }

    return templates.TemplateResponse("register_success.html", context)
