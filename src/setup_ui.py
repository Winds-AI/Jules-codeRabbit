from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from src.config import Settings
from src.dependencies import settings_dependency
from src.manifest import build_manifest
from src.utils.paths import TEMPLATES_DIR

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter()


@router.get("/setup", summary="Provide post-manifest setup guidance", response_class=HTMLResponse)
async def setup_page(
    request: Request, settings: Settings = Depends(settings_dependency)
) -> HTMLResponse:
    """Display end-to-end setup guidance and launch helpers for the GitHub App."""

    base_url = settings.normalized_base_url
    manifest = build_manifest(settings)
    manifest_json = json.dumps(manifest, separators=(",", ":"))
    manifest_url = f"{base_url}/github/manifest"
    register_url = f"{base_url}/github/register?code=<code>"
    webhook_url = f"{base_url}/github/webhook"
    repo_url = "https://github.com/Winds-AI/Jules-codeRabbit"

    env_variables = [
        {"name": "GITHUB_APP_ID", "note": "Value from the register success page"},
        {"name": "GITHUB_APP_SLUG", "note": "Value from the register success page"},
        {"name": "GITHUB_CLIENT_ID", "note": "Value from the register success page"},
        {"name": "GITHUB_CLIENT_SECRET", "note": "Value from the register success page"},
        {"name": "GITHUB_WEBHOOK_SECRET", "note": "Value from the register success page"},
        {"name": "GITHUB_PRIVATE_KEY", "note": "Paste PEM contents from the download"},
        {"name": "SERVICE_BASE_URL", "note": base_url},
    ]

    context = {
        "request": request,
        "base_url": base_url,
        "repo_url": repo_url,
        "manifest_url": manifest_url,
        "register_url": register_url,
        "webhook_url": webhook_url,
        "manifest_json": manifest_json,
        "manifest_launch_url": "https://github.com/settings/apps/new",
        "env_variables": env_variables,
        "quickstart_commands": [
            {
                "step": 1,
                "command": "python -m venv .venv",
                "description": "Create virtual environment"
            },
            {
                "step": 2,
                "command": "source .venv/bin/activate",
                "description": "Activate virtual environment (On Windows: .\\.venv\\Scripts\\Activate.ps1)"
            },
            {
                "step": 3,
                "command": "pip install -r requirements.txt",
                "description": "Install dependencies"
            },
            {
                "step": 4,
                "command": "cp .env.example .env",
                "description": "Copy .env.example to .env (On Windows CMD: copy .env.example .env)"
            },
            {
                "step": 5,
                "command": "python run.py",
                "description": "Start the application"
            },
        ],
    }

    return templates.TemplateResponse("setup.html", context)
