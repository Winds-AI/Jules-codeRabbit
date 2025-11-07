"""Queue job processor for GitHub review analysis."""

from __future__ import annotations

from typing import Any, Dict, List

from src.config import SettingsError, get_settings
from src.github_client import GitHubInstallationClient, GitHubAPIError
from src.jules_client import JulesAPIError, JulesClient
from src.logger import get_logger
from src.models.review import (
    PullRequestReviewContext,
    PushReviewContext,
    ReviewAnalysis,
    ReviewFinding,
    ReviewContext,
)
from src.queue.models import ReviewJob
from src.services.review_context import build_review_context

logger = get_logger()


class ReviewProcessor:
    async def __call__(self, job: ReviewJob) -> None:
        try:
            settings = get_settings()
            credentials = settings.require_code_review_credentials()
        except SettingsError as exc:  # pragma: no cover - configuration guard
            logger.error("Skipping job %s due to missing configuration: %s", job.delivery_id, exc)
            return

        github_client = GitHubInstallationClient(
            base_url=settings.normalized_github_api_base_url,
            app_id=credentials.github_app_id,
            private_key_pem=credentials.github_private_key_pem,
        )

        try:
            context = await build_review_context(github_client, job)
            logger.info(
                "Prepared %s review context for %s (files=%d)",
                job.event,
                context.repository,
                len(context.files),
            )

            jules_client = JulesClient(credentials.jules_api_key)
            try:
                analysis = await jules_client.analyze(context)
            except JulesAPIError as exc:
                logger.error("Jules analysis failed for %s: %s", context.repository, exc)
                return
            finally:
                await jules_client.aclose()

            if not analysis.comments and not analysis.summary:
                logger.info("No findings reported by Jules for %s", context.repository)
                return

            await self._publish_results(github_client, context, analysis)
        finally:
            await github_client.aclose()

    async def _publish_results(
        self,
        github_client: GitHubInstallationClient,
        context: ReviewContext,
        analysis: ReviewAnalysis,
    ) -> None:
        try:
            if isinstance(context, PullRequestReviewContext):
                await self._publish_pull_request_review(github_client, context, analysis)
            elif isinstance(context, PushReviewContext):
                await self._publish_push_review(github_client, context, analysis)
            else:  # pragma: no cover - defensive branch
                logger.warning("Unsupported review context type: %s", type(context))
        except GitHubAPIError as exc:
            logger.error("Failed to post review comments to GitHub: %s", exc)

    async def _publish_pull_request_review(
        self,
        github_client: GitHubInstallationClient,
        context: PullRequestReviewContext,
        analysis: ReviewAnalysis,
    ) -> None:
        comments_payload = [
            _build_pr_comment_payload(finding)
            for finding in analysis.comments
            if finding.path and finding.start_line
        ]

        summary_body = _format_summary_body(analysis.summary, analysis.comments)

        if not comments_payload and not summary_body:
            logger.info(
                "Jules produced no actionable comments for PR #%s",
                context.pull_number,
            )
            return

        logger.info(
            "Submitting review for PR #%s with %d inline comments.",
            context.pull_number,
            len(comments_payload),
        )

        await github_client.create_pull_request_review(
            installation_id=context.installation_id,
            full_name=context.repository,
            pull_number=context.pull_number,
            body=summary_body,
            comments=comments_payload,
        )

    async def _publish_push_review(
        self,
        github_client: GitHubInstallationClient,
        context: PushReviewContext,
        analysis: ReviewAnalysis,
    ) -> None:
        target_commit = context.after or (context.commits[-1] if context.commits else None)
        if not target_commit:
            logger.warning("Push review missing target commit SHA; skipping comment publish.")
            return

        for finding in analysis.comments:
            body = _format_comment_body(finding)
            await github_client.create_commit_comment(
                installation_id=context.installation_id,
                full_name=context.repository,
                commit_sha=target_commit,
                body=body,
                path=finding.path,
                line=finding.start_line,
            )

        if analysis.summary:
            summary_body = _format_summary_body(analysis.summary, analysis.comments)
            await github_client.create_commit_comment(
                installation_id=context.installation_id,
                full_name=context.repository,
                commit_sha=target_commit,
                body=summary_body,
            )


def _build_pr_comment_payload(finding: ReviewFinding) -> Dict[str, Any]:
    line = finding.end_line or finding.start_line
    payload: Dict[str, Any] = {
        "path": finding.path,
        "body": _format_comment_body(finding),
        "line": line,
        "side": "RIGHT",
    }
    if finding.end_line and finding.end_line != finding.start_line:
        payload["start_line"] = finding.start_line
        payload["start_side"] = "RIGHT"
    return payload


def _format_comment_body(finding: ReviewFinding) -> str:
    severity_line = f"**Severity:** {finding.severity.capitalize()}" if finding.severity else None
    parts = [finding.message.strip()]
    if severity_line:
        parts.append(severity_line)
    return "\n\n".join(parts)


def _format_summary_body(summary: str | None, findings: List[ReviewFinding]) -> str | None:
    summary = (summary or "").strip()
    if not summary and not findings:
        return None

    severity_counts: Dict[str, int] = {}
    for finding in findings:
        if finding.severity:
            key = finding.severity.lower()
        else:
            key = "unspecified"
        severity_counts[key] = severity_counts.get(key, 0) + 1

    lines = []
    if summary:
        lines.append(summary)
    if severity_counts:
        counts_line = ", ".join(f"{count} {level}" for level, count in severity_counts.items())
        lines.append(f"Findings by severity: {counts_line}")
    return "\n\n".join(lines).strip() or None

