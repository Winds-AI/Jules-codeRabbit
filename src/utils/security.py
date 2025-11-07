"""Security helpers for webhook validation and secret handling."""

from __future__ import annotations

import hashlib
import hmac


def build_github_signature(secret: str, payload: bytes) -> str:
    """Return the GitHub-style HMAC signature for the given payload."""

    digest = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def verify_github_signature(secret: str, payload: bytes, raw_signature: str | None) -> bool:
    """Verify a GitHub webhook signature using a constant-time comparison."""

    if not raw_signature:
        return False

    expected_signature = build_github_signature(secret, payload)
    return hmac.compare_digest(expected_signature, raw_signature)

