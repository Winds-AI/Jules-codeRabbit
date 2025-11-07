"""GitHub API client helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List

import httpx
import jwt


class GitHubAPIError(RuntimeError):
    """Raised when a GitHub API request fails."""

    def __init__(self, message: str, status_code: int, response_body: Any | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


DEFAULT_ACCEPT_HEADER = "application/vnd.github+json"
DEFAULT_API_VERSION = "2022-11-28"


class GitHubAppClient:
    """Lightweight client for GitHub App manifest conversion."""

    def __init__(
        self,
        *,
        base_url: str,
        timeout: float = 10.0,
        user_agent: str = "CodeReviewBot-Manifest/1.0",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._user_agent = user_agent
        self._client: httpx.AsyncClient | None = client
        self._owns_client = client is None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout,
                headers={
                    "User-Agent": self._user_agent,
                    "Accept": DEFAULT_ACCEPT_HEADER,
                    "X-GitHub-Api-Version": DEFAULT_API_VERSION,
                },
            )
        return self._client

    async def convert_manifest(self, code: str) -> Dict[str, Any]:
        """Exchange a manifest code for GitHub App credentials."""

        url = f"/app-manifests/{code}/conversions"
        client = self._get_client()
        response = await client.post(url)

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

    async def aclose(self) -> None:
        """Close the underlying HTTP client if this instance owns it."""

        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None


@dataclass
class InstallationToken:
    token: str
    expires_at: datetime
    permissions: Dict[str, Any] | None = None

    def is_active(self, *, skew_seconds: int = 60) -> bool:
        """Return True if the token is still valid accounting for clock skew."""

        return self.expires_at - timedelta(seconds=skew_seconds) > datetime.now(timezone.utc)


class GitHubInstallationClient:
    """GitHub App helper for installation-scoped API operations."""

    def __init__(
        self,
        *,
        base_url: str,
        app_id: int,
        private_key_pem: str,
        timeout: float = 10.0,
        user_agent: str = "Jules-CodeReviewer/1.0",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._user_agent = user_agent
        self._app_id = app_id
        # Normalize private key: handle escaped newlines from environment variables
        self._private_key = private_key_pem.replace("\\n", "\n")
        self._client = client or httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout,
            headers={
                "User-Agent": self._user_agent,
                "Accept": DEFAULT_ACCEPT_HEADER,
                "X-GitHub-Api-Version": DEFAULT_API_VERSION,
            },
        )
        self._owns_client = client is None
        self._installation_tokens: Dict[int, InstallationToken] = {}

    def _build_jwt(self) -> str:
        now = datetime.now(timezone.utc)
        payload = {
            "iat": int((now - timedelta(seconds=60)).timestamp()),
            "exp": int((now + timedelta(minutes=10)).timestamp()),
            "iss": self._app_id,
        }
        try:
            return jwt.encode(payload, self._private_key, algorithm="RS256")
        except Exception as exc:
            raise GitHubAPIError(
                f"Failed to encode JWT: {exc}. Check that GITHUB_PRIVATE_KEY is a valid RSA private key in PEM format.",
                0,
                None,
            ) from exc

    def _app_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._build_jwt()}",
            "Accept": DEFAULT_ACCEPT_HEADER,
            "X-GitHub-Api-Version": DEFAULT_API_VERSION,
        }

    @staticmethod
    def _installation_headers(token: str) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "Accept": DEFAULT_ACCEPT_HEADER,
            "X-GitHub-Api-Version": DEFAULT_API_VERSION,
        }

    async def _request(
        self,
        method: str,
        url: str,
        *,
        headers: Dict[str, str],
        params: Dict[str, Any] | None = None,
        json: Any | None = None,
    ) -> httpx.Response:
        response = await self._client.request(method, url, headers=headers, params=params, json=json)
        if response.status_code >= 400:
            detail: Any | None
            if response.content:
                try:
                    detail = response.json()
                except ValueError:
                    detail = response.text
            else:
                detail = None
            raise GitHubAPIError(
                f"GitHub API request to {url} failed with status {response.status_code}.",
                response.status_code,
                detail,
            )
        return response

    async def _fetch_installation_token(
        self, installation_id: int, permissions: Dict[str, Any] | None = None
    ) -> InstallationToken:
        payload = {"permissions": permissions} if permissions else None
        response = await self._request(
            "POST",
            f"/app/installations/{installation_id}/access_tokens",
            headers=self._app_headers(),
            json=payload,
        )
        data = response.json()
        token_value = data.get("token")
        if not token_value:
            raise GitHubAPIError(
                "GitHub did not return an installation token.",
                response.status_code,
                data,
            )

        expires_at_raw = data.get("expires_at")
        if not expires_at_raw:
            raise GitHubAPIError(
                "GitHub did not return an expires_at value for installation token.",
                response.status_code,
                data,
            )
        expires_at = _parse_github_timestamp(expires_at_raw)
        return InstallationToken(
            token=token_value,
            expires_at=expires_at,
            permissions=data.get("permissions"),
        )

    async def get_installation_token(
        self, installation_id: int, permissions: Dict[str, Any] | None = None
    ) -> InstallationToken:
        cached = self._installation_tokens.get(installation_id)
        if cached and cached.is_active():
            return cached

        token = await self._fetch_installation_token(installation_id, permissions)
        self._installation_tokens[installation_id] = token
        return token

    @staticmethod
    def _split_full_name(full_name: str) -> tuple[str, str]:
        if "/" not in full_name:
            raise ValueError(f"Repository full name '{full_name}' is invalid.")
        owner, repo = full_name.split("/", 1)
        return owner, repo

    async def get_commit_compare(
        self,
        *,
        installation_id: int,
        full_name: str,
        base: str,
        head: str,
    ) -> Dict[str, Any]:
        token = await self.get_installation_token(installation_id)
        owner, repo = self._split_full_name(full_name)
        response = await self._request(
            "GET",
            f"/repos/{owner}/{repo}/compare/{base}...{head}",
            headers=self._installation_headers(token.token),
        )
        return response.json()

    async def list_pull_request_files(
        self,
        *,
        installation_id: int,
        full_name: str,
        pull_number: int,
    ) -> List[Dict[str, Any]]:
        token = await self.get_installation_token(installation_id)
        owner, repo = self._split_full_name(full_name)

        files: List[Dict[str, Any]] = []
        page = 1
        while True:
            response = await self._request(
                "GET",
                f"/repos/{owner}/{repo}/pulls/{pull_number}/files",
                headers=self._installation_headers(token.token),
                params={"per_page": 100, "page": page},
            )
            batch = response.json()
            if not isinstance(batch, list):
                raise GitHubAPIError(
                    "Unexpected response while listing pull request files.",
                    response.status_code,
                    batch,
                )
            files.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return files

    async def create_pull_request_review(
        self,
        *,
        installation_id: int,
        full_name: str,
        pull_number: int,
        body: str | None,
        comments: Iterable[Dict[str, Any]],
        event: str = "COMMENT",
    ) -> Dict[str, Any]:
        token = await self.get_installation_token(installation_id)
        owner, repo = self._split_full_name(full_name)
        payload: Dict[str, Any] = {"event": event, "comments": list(comments)}
        if body:
            payload["body"] = body
        response = await self._request(
            "POST",
            f"/repos/{owner}/{repo}/pulls/{pull_number}/reviews",
            headers=self._installation_headers(token.token),
            json=payload,
        )
        return response.json()

    async def create_commit_comment(
        self,
        *,
        installation_id: int,
        full_name: str,
        commit_sha: str,
        body: str,
        path: str | None = None,
        position: int | None = None,
        line: int | None = None,
    ) -> Dict[str, Any]:
        token = await self.get_installation_token(installation_id)
        owner, repo = self._split_full_name(full_name)
        payload: Dict[str, Any] = {"body": body}
        if path:
            payload["path"] = path
        if position is not None:
            payload["position"] = position
        if line is not None:
            payload["line"] = line
        response = await self._request(
            "POST",
            f"/repos/{owner}/{repo}/commits/{commit_sha}/comments",
            headers=self._installation_headers(token.token),
            json=payload,
        )
        return response.json()

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None


def _parse_github_timestamp(raw: str) -> datetime:
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    return datetime.fromisoformat(raw).astimezone(timezone.utc)
