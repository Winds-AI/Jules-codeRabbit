from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException

from src.config import Settings
from src.dependencies import settings_dependency

router = APIRouter()

DEFAULT_PERMISSIONS: Dict[str, str] = {
    "contents": "read",
    "metadata": "read",
    "pull_requests": "write",
    "issues": "write",
    "commit_statuses": "write",
}
DEFAULT_EVENTS: List[str] = ["push", "pull_request", "installation"]


@router.get("/manifest", summary="Return GitHub App manifest")
async def get_manifest(settings: Settings = Depends(settings_dependency)) -> Dict[str, Any]:
    """Return a GitHub App manifest derived from runtime configuration."""

    base_url = settings.normalized_base_url
    register_url = f"{base_url}/github/register"
    webhook_url = f"{base_url}/github/webhook"

    if settings.manifest_public and not base_url.startswith("https://"):
        raise HTTPException(
            status_code=500,
            detail="SERVICE_BASE_URL must use https when MANIFEST_PUBLIC=true.",
        )

    manifest: Dict[str, Any] = {
        "name": "CodeReviewBot",
        "description": "Automated GitHub pull request reviews powered by Google Jules.",
        "url": base_url,
        "hook_attributes": {"url": webhook_url},
        "redirect_url": register_url,
        "callback_urls": [base_url],
        "public": settings.manifest_public,
        "default_permissions": DEFAULT_PERMISSIONS.copy(),
        "default_events": DEFAULT_EVENTS.copy(),
        "setup_url": f"{base_url}/setup",
    }

    return manifest
