"""Manual Jules session debugger.

This script mirrors the service's Jules integration so you can inspect the
raw API payloads that arrive during a session. Provide a serialized
``ReviewContext`` (either push or pull request) and the script will:

1. Build the same prompt we send in production.
2. Create a session with Jules.
3. Poll the activities feed, printing each payload.
4. Show any JSON fragments returned by the agent.

Usage example:

    python -m scripts.debug_jules_session \
        --context-file ./tmp/context.json \
        --api-key "$JULES_API_KEY"

The context file must be a JSON object shaped like one of the
``PushReviewContext`` or ``PullRequestReviewContext`` dataclasses in
``src.models.review``. See ``load_context`` below for the accepted schema.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict

import httpx

from src.jules_client import (
    JulesAPIError,
    JulesClient,
    _build_prompt,
    _extract_agent_messages,
    _extract_json_fragment,
    _raise_for_status,
)
from src.models.review import (
    FilePatch,
    PullRequestReviewContext,
    PushReviewContext,
    ReviewContext,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a Jules session and dump raw responses")
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument(
        "--context-file",
        type=Path,
        help="Path to a JSON file describing the review context (push or pull_request)",
    )
    source_group.add_argument(
        "--webhook-payload",
        type=Path,
        help="Path to a JSON webhook payload from GitHub (push events supported)",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="Jules API key. If omitted, the script falls back to the JULES_API_KEY env var.",
    )
    parser.add_argument(
        "--github-token",
        default=None,
        help=(
            "GitHub token used to fetch compare diffs when providing --webhook-payload. "
            "Falls back to GITHUB_TOKEN env var."
        ),
    )
    parser.add_argument(
        "--base-url",
        default="https://jules.googleapis.com/v1alpha",
        help="Base URL for the Jules API",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="HTTP timeout in seconds",
    )
    parser.add_argument(
        "--attempts",
        type=int,
        default=10,
        help="Maximum polling attempts",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.5,
        help="Base delay (seconds) between polling attempts",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=50,
        help="Page size to request when listing activities",
    )
    parser.add_argument(
        "--title",
        default=None,
        help="Optional session title override",
    )
    return parser.parse_args()


def load_context(path: Path) -> ReviewContext:
    raw = json.loads(path.read_text())
    context_type = raw.get("type")
    if context_type not in {"push", "pull_request"}:
        raise ValueError("Context JSON must include 'type' of 'push' or 'pull_request'")

    files = [
        FilePatch(
            path=entry["path"],
            status=entry["status"],
            additions=int(entry.get("additions", 0)),
            deletions=int(entry.get("deletions", 0)),
            patch=entry.get("patch"),
        )
        for entry in raw.get("files", [])
    ]

    if context_type == "push":
        return PushReviewContext(
            repository=raw["repository"],
            installation_id=int(raw["installation_id"]),
            ref=raw.get("ref"),
            before=raw.get("before"),
            after=raw.get("after"),
            commits=[str(c) for c in raw.get("commits", [])],
            files=files,
            compare_url=raw.get("compare_url"),
        )

    return PullRequestReviewContext(
        repository=raw["repository"],
        installation_id=int(raw["installation_id"]),
        pull_number=int(raw["pull_number"]),
        title=raw.get("title"),
        head_sha=raw.get("head_sha"),
        base_sha=raw.get("base_sha"),
        head_ref=raw.get("head_ref"),
        files=files,
        url=raw.get("url"),
    )


async def load_context_from_push_event(path: Path, token: str | None) -> PushReviewContext:
    payload = json.loads(path.read_text())
    repo = payload["repository"]
    full_name = repo["full_name"]
    owner, name = full_name.split("/", 1)
    before = payload.get("before")
    after = payload.get("after")
    installation_id = int(payload["installation"]["id"])
    ref = payload.get("ref")
    compare_url = payload.get("compare")
    commits = [commit.get("id") for commit in payload.get("commits", []) if commit.get("id")]

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "debug-jules-session",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    compare_endpoint = f"https://api.github.com/repos/{owner}/{name}/compare/{before}...{after}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(compare_endpoint, headers=headers)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:  # pragma: no cover - diagnostic helper
            print(
                f"Failed to fetch compare diff from GitHub: {exc.response.status_code} {exc.response.text}",
                file=sys.stderr,
            )
            raise
        compare_data = response.json()

    files_data = compare_data.get("files", [])
    files = [
        FilePatch(
            path=entry.get("filename"),
            status=entry.get("status", "modified"),
            additions=int(entry.get("additions", 0)),
            deletions=int(entry.get("deletions", 0)),
            patch=entry.get("patch"),
        )
        for entry in files_data
        if entry.get("filename")
    ]

    return PushReviewContext(
        repository=full_name,
        installation_id=installation_id,
        ref=ref,
        before=before,
        after=after,
        commits=commits,
        files=files,
        compare_url=compare_url,
    )


async def create_and_poll(
    context: ReviewContext,
    *,
    api_key: str,
    base_url: str,
    timeout: float,
    title: str | None,
    attempts: int,
    delay: float,
    page_size: int,
) -> None:
    client = JulesClient(api_key, base_url=base_url, timeout=timeout)
    session_name: str | None = None
    try:
        prompt = _build_prompt(context)
        session_title = title or f"Manual review debug for {context.repository}"
        print("=== Prompt (truncated to 2000 chars) ===")
        preview = prompt if len(prompt) <= 2000 else prompt[:2000] + "\n…"
        print(preview)
        print()

        print("=== Creating session ===")
        session = await client._create_session(context, prompt, title=session_title)
        print(json.dumps(session, indent=2))
        print()

        session_name = session.get("name")
        if not session_name:
            print("Session response did not include a 'name' field; aborting", file=sys.stderr)
            return

        print(f"Polling activities for {session_name} (attempts={attempts}, delay={delay}s)")
        max_404_retries = 3
        last_error: Exception | None = None

        for attempt in range(attempts):
            attempt_no = attempt + 1
            try:
                response = await client._client.get(
                    f"/{session_name}/activities",
                    params={"pageSize": page_size},
                )
                _raise_for_status("list activities", response)
                payload: Dict[str, Any] = response.json()
            except JulesAPIError as exc:
                last_error = exc
                message = str(exc)
                if ("404" in message or "NOT_FOUND" in message) and attempt < max_404_retries:
                    wait_time = delay * 2 * attempt_no
                    print(
                        f"[{attempt_no}] activities 404 — session may still be initializing; retrying in {wait_time:.2f}s",
                        file=sys.stderr,
                    )
                    await asyncio.sleep(wait_time)
                    continue
                if "429" in message or "RATE_LIMIT" in message:
                    wait_time = delay * (2 ** attempt)
                    print(f"[{attempt_no}] rate limited; sleeping {wait_time:.2f}s", file=sys.stderr)
                    await asyncio.sleep(wait_time)
                    continue
                if "500" in message or "INTERNAL" in message:
                    wait_time = delay * attempt_no
                    print(f"[{attempt_no}] server error; sleeping {wait_time:.2f}s", file=sys.stderr)
                    await asyncio.sleep(wait_time)
                    continue
                raise

            print(f"--- Activities payload (attempt {attempt_no}) ---")
            activities = payload.get("activities", [])
            print(f"Total activities: {len(activities)}")
            if activities:
                print(json.dumps(payload, indent=2))
            else:
                print("{}")
            
            # Also check session state
            try:
                session_response = await client._client.get(f"/{session_name}")
                _raise_for_status("get session", session_response)
                session_data = session_response.json()
                print(f"--- Session state (attempt {attempt_no}) ---")
                print(f"State: {session_data.get('state', 'UNKNOWN')}")
                print(f"Update time: {session_data.get('updateTime', 'N/A')}")
            except Exception as exc:
                print(f"Failed to get session state: {exc}")

            print("\n--- Extracted agent messages ---")
            agent_texts = list(_extract_agent_messages(payload))
            if agent_texts:
                for idx, text in enumerate(agent_texts):
                    print(f"\n>>> Agent fragment {idx + 1} >>>")
                    print(text[:500] + "..." if len(text) > 500 else text)
                    if parsed := _extract_json_fragment(text):
                        print("\n### Parsed JSON fragment ###")
                        try:
                            parsed_json = json.loads(parsed)
                            print(json.dumps(parsed_json, indent=2))
                            print("\n✓ JSON successfully extracted!")
                            return
                        except json.JSONDecodeError:
                            print(parsed)
            else:
                print("No agent messages found")
            print("\n" + "="*60 + "\n")

            if attempt < attempts - 1:
                wait_time = delay * (attempt_no) / attempts
                await asyncio.sleep(wait_time)

        print("Polling completed with no JSON fragment detected.")
        if last_error:
            print(f"Last error: {last_error}")
    finally:
        await client.aclose()


async def async_main() -> None:
    from os import getenv

    args = parse_args()

    api_key = args.api_key or getenv("JULES_API_KEY")
    if not api_key:
        print("A Jules API key must be provided via --api-key or JULES_API_KEY", file=sys.stderr)
        sys.exit(1)

    github_token = args.github_token or getenv("GITHUB_TOKEN")

    try:
        if args.context_file:
            context = load_context(args.context_file)
        else:
            context = await load_context_from_push_event(args.webhook_payload, github_token)
    except Exception as exc:  # pragma: no cover - diagnostic helper
        print(f"Failed to load context: {exc}", file=sys.stderr)
        sys.exit(1)

    await create_and_poll(
        context,
        api_key=api_key,
        base_url=args.base_url,
        timeout=args.timeout,
        title=args.title,
        attempts=args.attempts,
        delay=args.delay,
        page_size=args.page_size,
    )


if __name__ == "__main__":  # pragma: no cover - script entry point
    asyncio.run(async_main())

