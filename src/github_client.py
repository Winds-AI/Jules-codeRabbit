"""GitHub API client helpers."""

from __future__ import annotations

from typing import Any, Dict

import httpx


class GitHubAPIError(RuntimeError):
    """Raised when a GitHub API request fails."""

    def __init__(self, message: str, status_code: int, response_body: Any | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class GitHubAppClient:
    """Lightweight client for GitHub App manifest conversion."""

    def __init__(
        self,
        *,
        base_url: str,
        timeout: float = 10.0,
        user_agent: str = "CodeReviewBot-Manifest/1.0",
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._user_agent = user_agent

    async def convert_manifest(self, code: str) -> Dict[str, Any]:
        """Exchange a manifest code for GitHub App credentials."""

        url = f"{self._base_url}/app-manifests/{code}/conversions"
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": self._user_agent,
        }

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(url, headers=headers)

        if response.status_code >= 400:
            detail: Any | None
            if response.content:
                try:
                    detail = response.json()
                except ValueError:
                    detail = response.text
            else:
                detail = None
            message = (
                f"GitHub API responded with status {response.status_code} during manifest conversion."
            )
            raise GitHubAPIError(message, response.status_code, detail)

        try:
            return response.json()
        except ValueError as exc:  # pragma: no cover - defensive branch
            raise GitHubAPIError(
                "GitHub API returned invalid JSON during manifest conversion.",
                response.status_code,
                response.text,
            ) from exc
