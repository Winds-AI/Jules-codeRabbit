"""Client wrapper for interacting with the Jules API."""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any, Dict, Iterable, List

import httpx

from src.logger import get_logger, log_with_context, log_timing, log_failure
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
        ctx_logger = log_with_context(logger, repository=context.repository)
        ctx_logger.debug(f"Building prompt ({len(context.files)} files)")
        
        with log_timing(ctx_logger, "build_prompt"):
            prompt = _build_prompt(context)
        ctx_logger.debug(f"Prompt built: {len(prompt)} characters")

        ctx_logger.info("Creating Jules session")
        try:
            with log_timing(ctx_logger, "create_jules_session"):
                session = await self._create_session(context, prompt, title=f"Code review for {context.repository}")
        except JulesAPIError as exc:
            log_failure(logger, f"Failed to create Jules session: {exc}", exc, repository=context.repository)
            raise
        
        session_id = session.get("name")
        if not session_id:
            log_failure(logger, "Jules session did not return an identifier", repository=context.repository)
            logger.error(f"Session creation response: {session}")
            raise JulesAPIError("Jules session did not return an identifier.")

        session_ctx_logger = log_with_context(logger, repository=context.repository, session_id=session_id)
        session_ctx_logger.info(f"Created Jules session: {session_id}")

        # Add a brief delay to allow session initialization before polling
        session_ctx_logger.debug("Waiting for session to initialize before polling")
        await asyncio.sleep(2.0)

        session_ctx_logger.info("Polling for Jules response")
        try:
            with log_timing(session_ctx_logger, "poll_jules_response"):
                raw_response = await self._poll_for_response(session_id, logger=session_ctx_logger)
        except JulesAPIError as exc:
            log_failure(logger, f"Failed to poll Jules session: {exc}", exc, 
                       repository=context.repository, session_id=session_id)
            raise
        
        if not raw_response:
            session_ctx_logger.warning("Jules returned no analysis")
            return ReviewAnalysis()

        session_ctx_logger.debug(f"Parsing Jules response ({len(raw_response)} characters)")
        try:
            analysis = _parse_analysis(raw_response)
        except Exception as exc:
            log_failure(logger, f"Failed to parse Jules response: {exc}", exc, 
                       repository=context.repository, session_id=session_id)
            raise JulesAPIError("Unable to parse Jules response into review findings.") from exc
        
        if not analysis:
            log_failure(logger, "Jules response parsed but produced no analysis", 
                       repository=context.repository, session_id=session_id)
            raise JulesAPIError("Unable to parse Jules response into review findings.")
        
        session_ctx_logger.info(f"Jules analysis parsed: {len(analysis.comments)} comments, "
                               f"summary={'yes' if analysis.summary else 'no'}")
        return analysis

    async def _create_session(self, context: ReviewContext, prompt: str, *, title: str) -> Dict[str, Any]:
        ctx_logger = log_with_context(logger, repository=context.repository)
        
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

        source_path = source_context.get("source")
        ctx_logger.info(f"Creating Jules session for source: {source_path}")
        
        request_body = {
            "prompt": prompt,
            "title": title,
            "sourceContext": source_context,
        }
        ctx_logger.debug(f"Session request: source={source_path}, "
                         f"prompt_length={len(prompt)}, has_branch={'startingBranch' in github_repo_context}")
        
        try:
            response = await self._client.post(
                "/sessions",
                json=request_body,
            )
            _raise_for_status("create session", response)
            session_response = response.json()
            ctx_logger.debug("Session created successfully")
            return session_response
        except JulesAPIError as exc:
            # Categorize errors
            error_str = str(exc)
            if "400" in error_str or "BAD_REQUEST" in error_str:
                ctx_logger.error(f"Invalid session request (400): {exc}")
            elif "401" in error_str or "UNAUTHORIZED" in error_str:
                ctx_logger.error(f"Authentication failed (401): {exc}")
            elif "403" in error_str or "FORBIDDEN" in error_str:
                ctx_logger.error(f"Permission denied (403): {exc}")
            elif "500" in error_str or "INTERNAL" in error_str:
                ctx_logger.error(f"Jules server error (500): {exc}")
            else:
                ctx_logger.error(f"Jules API error: {exc}")
            raise

    async def _send_message(self, session_id: str, prompt: str) -> None:
        response = await self._client.post(
            f"/{session_id}:sendMessage",
            json={"prompt": prompt},
        )
        _raise_for_status("send message", response)

    async def _poll_for_response(self, session_id: str, *, attempts: int = 10, delay: float = 1.5, logger=None) -> str | None:
        if logger is None:
            logger = globals()['logger']
        
        ctx_logger = log_with_context(logger, session_id=session_id)
        ctx_logger.debug(f"Starting to poll for activities (max {attempts} attempts)")
        
        # Allow retries on 404 for the first few attempts (session initialization delay)
        max_404_retries = 3
        last_error = None
        
        for attempt in range(attempts):
            attempt_start = time.time()
            ctx_logger.debug(f"Polling attempt {attempt + 1}/{attempts}")
            
            try:
                response = await self._client.get(
                    f"/{session_id}/activities",
                    params={"pageSize": 50},
                )
                _raise_for_status("list activities", response)
                response_data = response.json()
                activities_count = len(response_data.get("activities", []))
                attempt_duration = time.time() - attempt_start
                ctx_logger.debug(f"Received {activities_count} activities (took {attempt_duration:.3f}s)")
            except JulesAPIError as exc:
                attempt_duration = time.time() - attempt_start
                last_error = exc
                error_str = str(exc)
                
                # Handle 404 errors (session not found)
                if "404" in error_str or "NOT_FOUND" in error_str:
                    if attempt < max_404_retries:
                        # Transient initialization delay - retry with exponential backoff
                        sleep_time = delay * 2 * (attempt + 1)
                        ctx_logger.warning(
                            f"Session not found (404) on attempt {attempt + 1} - "
                            f"may be initializing. Retrying in {sleep_time:.2f}s..."
                        )
                        await asyncio.sleep(sleep_time)
                        continue
                    else:
                        # Permanent 404 after retries
                        ctx_logger.error(
                            f"Session not found (404) after {attempt + 1} attempts. "
                            f"This likely indicates the source repository doesn't exist in Jules or the session is invalid."
                        )
                        raise JulesAPIError(
                            f"Session not found after {attempt + 1} attempts. "
                            f"The repository source may not be registered in Jules, "
                            f"or the session was created with invalid parameters. Original error: {exc}"
                        ) from exc
                elif "429" in error_str or "RATE_LIMIT" in error_str:
                    # Rate limit - use exponential backoff
                    sleep_time = delay * (2 ** attempt)
                    ctx_logger.warning(f"Rate limit (429) on attempt {attempt + 1}. Waiting {sleep_time:.2f}s...")
                    await asyncio.sleep(sleep_time)
                    continue
                elif "500" in error_str or "INTERNAL" in error_str:
                    # Server error - retry with backoff
                    if attempt < attempts - 1:
                        sleep_time = delay * (attempt + 1)
                        ctx_logger.warning(f"Jules server error (500) on attempt {attempt + 1}. Retrying in {sleep_time:.2f}s...")
                        await asyncio.sleep(sleep_time)
                        continue
                    else:
                        ctx_logger.error(f"Jules server error (500) after {attempt + 1} attempts")
                        raise
                else:
                    # Other errors - fail immediately
                    ctx_logger.error(f"Jules API error on attempt {attempt + 1}: {exc}")
                    raise
            
            # Check for agent messages in activities
            for text in _extract_agent_messages(response_data):
                if parsed := _extract_json_fragment(text):
                    ctx_logger.info(f"Found JSON response in activities on attempt {attempt + 1}")
                    return parsed
            
            # No response yet, wait before next attempt
            if attempt < attempts - 1:
                sleep_time = delay * (attempt + 1) / attempts
                ctx_logger.debug(f"No response yet, sleeping {sleep_time:.2f}s before next attempt")
                await asyncio.sleep(sleep_time)
        
        # No response after all attempts
        ctx_logger.warning(f"No response received after {attempts} attempts")
        if last_error:
            ctx_logger.debug(f"Last error was: {last_error}")
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

