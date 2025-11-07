"""Client wrapper for interacting with the Jules API."""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Dict, Iterable, List

import httpx

from src.logger import get_logger
from src.models.review import (
    PullRequestReviewContext,
    PushReviewContext,
    ReviewAnalysis,
    ReviewContext,
    ReviewFinding,
)

logger = get_logger()


class JulesAPIError(RuntimeError):
    """Raised when the Jules API responds with an error."""


class JulesClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://jules.googleapis.com/v1alpha",
        timeout: float = 30.0,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            headers={
                "X-Goog-Api-Key": api_key,
                "Content-Type": "application/json",
            },
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def analyze(self, context: ReviewContext) -> ReviewAnalysis:
        logger.debug(f"Building prompt for {context.repository} ({len(context.files)} files)")
        prompt = _build_prompt(context)
        logger.debug(f"Prompt built: {len(prompt)} characters")

        logger.info(f"Creating Jules session for {context.repository}")
        session = await self._create_session(context, prompt, title=f"Code review for {context.repository}")
        session_id = session.get("name")
        if not session_id:
            logger.error(f"Session creation response: {session}")
            raise JulesAPIError("Jules session did not return an identifier.")

        logger.info(f"Created Jules session: {session_id} for repository: {context.repository}")

        # When creating a session with a prompt, it starts processing immediately.
        # The sendMessage endpoint is for additional messages after session creation.
        # Since we already included the prompt in session creation, we skip sendMessage.
        # If you need to send additional messages later, you can call sendMessage separately.

        logger.info(f"Polling for Jules response from session: {session_id}")
        raw_response = await self._poll_for_response(session_id)
        if not raw_response:
            logger.warning(f"Jules returned no analysis for {context.repository}")
            return ReviewAnalysis()

        logger.debug(f"Parsing Jules response for {context.repository} ({len(raw_response)} characters)")
        analysis = _parse_analysis(raw_response)
        if not analysis:
            raise JulesAPIError("Unable to parse Jules response into review findings.")
        logger.info(f"Jules analysis parsed: {len(analysis.comments)} comments, summary={'yes' if analysis.summary else 'no'}")
        return analysis

    async def _create_session(self, context: ReviewContext, prompt: str, *, title: str) -> Dict[str, Any]:
        # Parse repository name (format: "owner/repo")
        repo_parts = context.repository.split("/", 1)
        if len(repo_parts) != 2:
            raise JulesAPIError(f"Invalid repository format: {context.repository}. Expected 'owner/repo'.")
        owner, repo = repo_parts

        # Build sourceContext
        source_context: Dict[str, Any] = {
            "source": f"sources/github/{owner}/{repo}",
        }

        # Add branch information if available
        github_repo_context: Dict[str, Any] = {}
        if isinstance(context, PushReviewContext) and context.ref:
            # Extract branch name from ref (format: "refs/heads/main" -> "main")
            if context.ref.startswith("refs/heads/"):
                branch = context.ref.replace("refs/heads/", "")
                github_repo_context["startingBranch"] = branch
        elif isinstance(context, PullRequestReviewContext) and context.head_ref:
            # For PRs, use the head branch ref directly (already in branch name format)
            github_repo_context["startingBranch"] = context.head_ref

        if github_repo_context:
            source_context["githubRepoContext"] = github_repo_context

        request_body = {
            "prompt": prompt,
            "title": title,
            "sourceContext": source_context,
        }
        logger.debug(f"Creating session with body: {json.dumps({**request_body, 'prompt': prompt[:100] + '...' if len(prompt) > 100 else prompt})}")
        logger.info(f"Creating Jules session for source: {source_context.get('source')}")
        
        response = await self._client.post(
            "/sessions",
            json=request_body,
        )
        _raise_for_status("create session", response)
        session_response = response.json()
        logger.debug(f"Session creation response: {session_response}")
        return session_response

    async def _send_message(self, session_id: str, prompt: str) -> None:
        response = await self._client.post(
            f"/{session_id}:sendMessage",
            json={"prompt": prompt},
        )
        _raise_for_status("send message", response)

    async def _poll_for_response(self, session_id: str, *, attempts: int = 10, delay: float = 1.5) -> str | None:
        logger.debug(f"Starting to poll for activities from session {session_id} (max {attempts} attempts)")
        for attempt in range(attempts):
            logger.debug(f"Polling attempt {attempt + 1}/{attempts} for session {session_id}")
            try:
                response = await self._client.get(
                    f"/{session_id}/activities",
                    params={"pageSize": 50},
                )
                _raise_for_status("list activities", response)
                response_data = response.json()
                activities_count = len(response_data.get("activities", []))
                logger.debug(f"Received {activities_count} activities from session {session_id}")
            except JulesAPIError as exc:
                # If we get a 404, it likely means the session doesn't exist or the source is invalid
                if "404" in str(exc) or "NOT_FOUND" in str(exc):
                    logger.error(
                        f"=== JULES: Session {session_id} not found (404) on attempt {attempt + 1}. "
                        f"This may indicate the source repository doesn't exist in Jules or the session is invalid. "
                        f"Error: {exc} ==="
                    )
                    raise JulesAPIError(
                        f"Session not found. The repository source may not be registered in Jules, "
                        f"or the session was created with invalid parameters. Original error: {exc}"
                    ) from exc
                logger.warning(f"Jules API error on attempt {attempt + 1}: {exc}")
                raise
            for text in _extract_agent_messages(response_data):
                if parsed := _extract_json_fragment(text):
                    logger.info(f"Found JSON response in activities from session {session_id} on attempt {attempt + 1}")
                    return parsed
            if attempt < attempts - 1:
                sleep_time = delay * (attempt + 1) / attempts
                logger.debug(f"No response yet, sleeping {sleep_time:.2f}s before next attempt")
                await asyncio.sleep(sleep_time)
        logger.warning(f"No response received after {attempts} attempts for session {session_id}")
        return None


def _raise_for_status(action: str, response: httpx.Response) -> None:
    if response.status_code < 400:
        return
    detail: Any | None
    try:
        detail = response.json()
    except ValueError:
        detail = response.text
    raise JulesAPIError(f"Failed to {action}: status={response.status_code}, detail={detail}")


def _build_prompt(context: ReviewContext) -> str:
    header: str
    if isinstance(context, PullRequestReviewContext):
        header = (
            f"Repository: {context.repository}\n"
            f"Pull Request: #{context.pull_number} — {context.title or 'untitled'}\n"
            f"Head SHA: {context.head_sha} | Base SHA: {context.base_sha}\n"
        )
    elif isinstance(context, PushReviewContext):
        commits = ", ".join(context.commits) if context.commits else "(no commit list)"
        header = (
            f"Repository: {context.repository}\n"
            f"Ref: {context.ref}\n"
            f"After: {context.after} | Before: {context.before}\n"
            f"Commits: {commits}\n"
        )
    else:  # pragma: no cover - defensive branch
        header = f"Repository: {context.repository}\n"

    files_instructions = _format_files_for_prompt(context)

    instructions = (
        "You are an automated code reviewer. Analyze the provided Git diff patches and "
        "return actionable findings. Respond *only* with valid JSON matching this schema:\n"
        "{\n"
        "  \"summary\": string,\n"
        "  \"comments\": [\n"
        "    {\n"
        "      \"path\": string,\n"
        "      \"start_line\": integer,\n"
        "      \"end_line\": integer|null,\n"
        "      \"message\": string,\n"
        "      \"severity\": one of [\"critical\", \"major\", \"minor\", \"info\"]\n"
        "    }\n"
        "  ]\n"
        "}\n"
        "Focus on bugs, security issues, or major regressions. Omit stylistic nitpicks."
    )

    return f"{instructions}\n\nContext:\n{header}\nDiffs:\n{files_instructions}".strip()


def _format_files_for_prompt(context: ReviewContext, *, max_files: int = 15, max_patch_chars: int = 4000) -> str:
    sections: List[str] = []
    for index, file in enumerate(context.files[:max_files]):
        patch = file.patch or "(no patch available)"
        if len(patch) > max_patch_chars:
            patch = patch[:max_patch_chars] + "\n... (truncated)"
        sections.append(f"### File {index + 1}: {file.path}\nStatus: {file.status}\nPatch:\n{patch}")
    if len(context.files) > max_files:
        sections.append(f"(Truncated to {max_files} files of {len(context.files)} total)")
    return "\n\n".join(sections)


def _extract_agent_messages(payload: Dict[str, Any]) -> Iterable[str]:
    for activity in payload.get("activities", []):
        if activity.get("originator") != "agent":
            continue

        messages = activity.get("messages") or []
        for message in messages:
            if text := message.get("text"):
                yield text

        progress = activity.get("progressUpdated")
        if progress and (description := progress.get("description")):
            yield description

        outputs = activity.get("outputs") or []
        for output in outputs:
            if pull_request := output.get("pullRequest"):
                if desc := pull_request.get("description"):
                    yield desc


def _extract_json_fragment(text: str) -> str | None:
    text = text.strip()
    if not text:
        return None

    if text.startswith("`"):
        match = re.search(r"```(?:json)?\s*(\{.*?\})```", text, re.DOTALL)
        if match:
            return match.group(1)

    if text.startswith("{") and text.endswith("}"):
        return text

    match = re.search(r"(\{.*\})", text, re.DOTALL)
    if match:
        return match.group(1)
    return None


def _parse_analysis(raw_json: str) -> ReviewAnalysis | None:
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError:
        return None

    comments_data = data.get("comments") or []
    findings: List[ReviewFinding] = []
    for entry in comments_data:
        try:
            path = entry.get("path")
            start_line = int(entry.get("start_line"))
            end_line_raw = entry.get("end_line")
            end_line = int(end_line_raw) if end_line_raw is not None else None
            message = entry.get("message")
            severity = entry.get("severity")
        except (TypeError, ValueError):
            continue

        if not path or not message:
            continue
        findings.append(
            ReviewFinding(
                path=path,
                start_line=start_line,
                end_line=end_line,
                message=message.strip(),
                severity=(severity or "").strip() or None,
            )
        )

    summary = data.get("summary")
    if isinstance(summary, str):
        summary = summary.strip()
    else:
        summary = None

    return ReviewAnalysis(comments=findings, summary=summary)

