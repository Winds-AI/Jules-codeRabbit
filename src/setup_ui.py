from __future__ import annotations

import html
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from src.config import Settings
from src.dependencies import settings_dependency

router = APIRouter()


@router.get("/setup", summary="Provide post-manifest setup guidance", response_class=HTMLResponse)
async def setup_page(settings: Settings = Depends(settings_dependency)) -> HTMLResponse:
    """Display manual setup instructions for newly created GitHub Apps."""

    base_url = settings.normalized_base_url

    content = f"""<!DOCTYPE html>
<html lang=\"en\">
<head>
    <meta charset=\"utf-8\" />
    <title>GitHub App Setup Checklist</title>
    <style>
        body {{ font-family: system-ui, -apple-system, BlinkMacSystemFont, \"Segoe UI\", sans-serif; margin: 2rem; line-height: 1.6; }}
        h1 {{ margin-bottom: 0.5rem; }}
        section {{ margin-top: 2rem; }}
        ol {{ padding-left: 1.25rem; }}
        code {{ background: #f6f8fa; padding: 0.2rem 0.4rem; border-radius: 4px; }}
        .env-list code {{ display: block; margin-bottom: 0.5rem; }}
        .note {{ background: #fff4e5; border-left: 4px solid #f59e0b; padding: 1rem 1.5rem; border-radius: 6px; }}
    </style>
</head>
<body>
    <h1>Finish Your GitHub App Setup</h1>
    <p>Use this checklist after completing the manifest flow. We do <strong>not</strong> store any credentials—keep your own secure copy.</p>
    <section>
        <h2>1. Create the GitHub App</h2>
        <ol>
            <li>Visit <code>{html.escape(base_url)}/github/manifest</code> and copy the JSON into the GitHub App creation form.</li>
            <li>After GitHub redirects back to <code>{html.escape(base_url)}/github/register?code=&lt;...&gt;</code>, copy the credentials shown on the success page.</li>
            <li>Download the PEM file immediately; it is not saved on this service.</li>
        </ol>
    </section>
    <section>
        <h2>2. Configure Your Deployment</h2>
        <p>Add the following environment variables to your hosting platform (Render, Docker, etc.). Replace placeholders with the values from the register page.</p>
        <div class=\"env-list\">
            <code>GITHUB_APP_ID=&lt;value from register page&gt;</code>
            <code>GITHUB_APP_SLUG=&lt;value from register page&gt;</code>
            <code>GITHUB_CLIENT_ID=&lt;value from register page&gt;</code>
            <code>GITHUB_CLIENT_SECRET=&lt;value from register page&gt;</code>
            <code>GITHUB_WEBHOOK_SECRET=&lt;value from register page&gt;</code>
            <code>GITHUB_PRIVATE_KEY=&lt;paste PEM contents&gt;</code>
            <code>SERVICE_BASE_URL={html.escape(base_url)}</code>
        </div>
        <p>If you host elsewhere, update the <code>SERVICE_BASE_URL</code> to match your deployed URL.</p>
    </section>
    <section>
        <h2>3. Next Steps</h2>
        <ol>
            <li>Install the GitHub App on the repositories you want to monitor.</li>
            <li>Provide the webhook URL <code>{html.escape(base_url)}/github/webhook</code> to GitHub when configuring the app.</li>
            <li>Keep your credentials safe; rotate them from the GitHub UI if exposed.</li>
        </ol>
    </section>
    <section class=\"note\">
        <h2>About Automation</h2>
        <p>This service currently focuses on the GitHub App creation flow. Webhook processing and Jules analysis are disabled for now.</p>
    </section>
</body>
</html>"""

    return HTMLResponse(content=content)
