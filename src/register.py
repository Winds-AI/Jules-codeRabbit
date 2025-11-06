from __future__ import annotations

import base64
import html
import json
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse

from src.config import Settings
from src.dependencies import settings_dependency
from src.github_client import GitHubAPIError, GitHubAppClient

router = APIRouter()


REQUIRED_CONVERSION_KEYS = {
    "id",
    "slug",
    "client_id",
    "client_secret",
    "webhook_secret",
}


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


def _render_success_page(conversion: Dict[str, Any], base_url: str) -> str:
    """Render an HTML page exposing manifest conversion credentials."""
    fields = {
        "App ID": conversion.get("id"),
        "Slug": conversion.get("slug"),
        "Client ID": conversion.get("client_id"),
        "Client Secret": conversion.get("client_secret"),
        "Webhook Secret": conversion.get("webhook_secret"),
    }

    pem_value = conversion.get("pem") or ""
    pem_section = ""
    if pem_value:
        pem_bytes = pem_value.encode("utf-8")
        pem_download_href = (
            "data:application/x-pem-file;base64," + base64.b64encode(pem_bytes).decode("ascii")
        )
        slug_value = str(conversion.get("slug") or "github-app").strip().replace(" ", "-")
        pem_filename = f"{slug_value}-private-key.pem"
        escaped_href = html.escape(pem_download_href, quote=True)
        escaped_filename = html.escape(pem_filename, quote=True)
        pem_section = f"""
        <section>
            <h2>Private Key (PEM)</h2>
            <p>This file is shown only once. Download and store it securely—we do not retain a copy.</p>
            <a class="download" href="{escaped_href}" download="{escaped_filename}">Download private key ({escaped_filename})</a>
        </section>
        """

    raw_json = html.escape(json.dumps(conversion, indent=2))

    summary_rows = "".join(
        f"<dt>{html.escape(label)}</dt><dd>{html.escape(str(value)) if value is not None else '<em>missing</em>'}</dd>"
        for label, value in fields.items()
    )

    security_notice = """
    <section class="notice">
        <h2>Security Notice</h2>
        <p>These credentials are displayed a single time. Store them in your deployment secrets immediately—we cannot recover them later.</p>
    </section>
    """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8" />
    <title>GitHub App Ready</title>
    <style>
        body {{ font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 2rem; line-height: 1.5; }}
        header {{ margin-bottom: 2rem; }}
        dl {{ display: grid; grid-template-columns: max-content 1fr; gap: 0.5rem 1.5rem; }}
        textarea {{ width: 100%; font-family: "SFMono-Regular", ui-monospace, "Roboto Mono", monospace; }}
        pre {{ background: #f6f8fa; padding: 1rem; border-radius: 6px; overflow-x: auto; }}
        section {{ margin-top: 2rem; }}
        section.notice {{ background: #fff4e5; border-left: 4px solid #f59e0b; padding: 1rem 1.5rem; border-radius: 6px; }}
        a.download {{ display: inline-block; margin-top: 0.75rem; padding: 0.75rem 1.25rem; background: #0366d6; color: #fff; border-radius: 6px; text-decoration: none; }}
        a.download:hover {{ background: #024ea2; }}
    </style>
</head>
<body>
    <header>
        <h1>GitHub App Created Successfully</h1>
        <p>Save the credentials below immediately. They are shown once per GitHub guidelines.</p>
        <p>Next, update your deployment’s environment variables so the app can authenticate with GitHub.</p>
    </header>
    {security_notice}
    <section>
        <h2>Key Credentials</h2>
        <dl>
            {summary_rows}
        </dl>
    </section>
    {pem_section}
    <section>
        <h2>Raw Response</h2>
        <pre>{raw_json}</pre>
    </section>
    <section>
        <h2>Continue Setup</h2>
        <ol>
            <li>Add the credentials above to your deployment secrets (Render, Docker, etc.).</li>
            <li>Configure your service base URL: <code>{html.escape(base_url)}</code></li>
            <li>Share the webhook URL: <code>{html.escape(base_url)}/github/webhook</code></li>
        </ol>
    </section>
</body>
</html>"""


@router.get(
    "/register",
    summary="Handle GitHub App manifest conversion callback",
    response_class=HTMLResponse,
)
async def register_app(
    code: str = Query(..., description="Temporary manifest code provided by GitHub."),
    settings: Settings = Depends(settings_dependency),
    github_client: GitHubAppClient = Depends(github_client_dependency),
) -> HTMLResponse:
    """Exchange the manifest code for GitHub App credentials and present them to the user."""

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

    html_content = _render_success_page(conversion, settings.normalized_base_url)
    return HTMLResponse(content=html_content)
