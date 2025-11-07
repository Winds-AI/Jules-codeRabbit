"""Queue job processor for GitHub review analysis."""

from __future__ import annotations

from typing import Any, Dict, List

from src.config import SettingsError, get_settings
from src.github_client import GitHubInstallationClient, GitHubAPIError
from src.jules_client import JulesAPIError, JulesClient
from src.logger import get_logger, log_with_context, log_timing, log_success, log_failure
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


class ReviewProcessorError(RuntimeError):
    """Raised when review processing fails."""
    
    def __init__(self, message: str, step: str, original_error: Exception | None = None):
        super().__init__(message)
        self.step = step
        self.original_error = original_error


class ReviewProcessor:
    async def __call__(self, job: ReviewJob) -> None:
        ctx_logger = log_with_context(logger, delivery_id=job.delivery_id, event_type=job.event)
        ctx_logger.info("=== PROCESSOR: Starting review processing ===")
        
        try:
            with log_timing(ctx_logger, "load_configuration"):
                settings = get_settings()
                credentials = settings.require_code_review_credentials()
                ctx_logger.debug("Settings and credentials loaded")
        except SettingsError as exc:  # pragma: no cover - configuration guard
            log_failure(logger, "Configuration missing", exc, delivery_id=job.delivery_id, event_type=job.event)
            raise ReviewProcessorError("Configuration incomplete", "load_configuration", exc) from exc

        github_client = None
        try:
            with log_timing(ctx_logger, "create_github_client"):
                github_client = GitHubInstallationClient(
                    base_url=settings.normalized_github_api_base_url,
                    app_id=credentials.github_app_id,
                    private_key_pem=credentials.github_private_key_pem,
                )
                ctx_logger.debug("GitHub client created")

            try:
                with log_timing(ctx_logger, "build_review_context"):
                    context = await build_review_context(github_client, job)
                    ctx_logger.info(f"Review context built successfully for {context.repository}")
            except GitHubAPIError as exc:
                log_failure(logger, f"Failed to build review context: {exc} (status={exc.status_code})", 
                          exc, delivery_id=job.delivery_id, event_type=job.event)
                raise ReviewProcessorError("Failed to build review context", "build_review_context", exc) from exc
            except (ValueError, TypeError) as exc:
                log_failure(logger, f"Invalid job payload: {exc}", exc, delivery_id=job.delivery_id, event_type=job.event)
                raise ReviewProcessorError("Invalid job payload", "build_review_context", exc) from exc

            repo_ctx_logger = log_with_context(logger, 
                                              delivery_id=job.delivery_id, 
                                              event_type=job.event,
                                              repository=context.repository)
            
            repo_ctx_logger.info(
                f"Prepared {job.event} review context (files={len(context.files)}, "
                f"installation_id={context.installation_id})"
            )

            jules_client = None
            analysis = None
            try:
                with log_timing(repo_ctx_logger, "jules_analysis"):
                    repo_ctx_logger.info("Creating Jules client")
                    jules_client = JulesClient(credentials.jules_api_key)
                    repo_ctx_logger.info("=== PROCESSOR: Starting Jules analysis ===")
                    analysis = await jules_client.analyze(context)
                    repo_ctx_logger.info(f"=== PROCESSOR: Jules analysis completed "
                                       f"(comments={len(analysis.comments)}, has_summary={bool(analysis.summary)}) ===")
            except JulesAPIError as exc:
                log_failure(logger, f"Jules analysis failed: {exc}", exc, 
                           delivery_id=job.delivery_id, event_type=job.event, repository=context.repository)
                raise ReviewProcessorError("Jules analysis failed", "jules_analysis", exc) from exc
            finally:
                if jules_client:
                    await jules_client.aclose()
                    repo_ctx_logger.debug("Jules client closed")

            if not analysis.comments and not analysis.summary:
                repo_ctx_logger.info("No findings reported by Jules - review complete")
                return

            with log_timing(repo_ctx_logger, "publish_results"):
                repo_ctx_logger.info(f"Publishing review results ({len(analysis.comments)} comments, "
                                  f"summary={'yes' if analysis.summary else 'no'})")
                await self._publish_results(github_client, context, analysis)
            
            log_success(logger, f"Review processing completed successfully for {context.repository}",
                       delivery_id=job.delivery_id, event_type=job.event, repository=context.repository)
        finally:
            if github_client:
                await github_client.aclose()
                ctx_logger.debug("GitHub client closed")

    async def _publish_results(
        self,
        github_client: GitHubInstallationClient,
        context: ReviewContext,
        analysis: ReviewAnalysis,
    ) -> None:
        ctx_logger = log_with_context(logger, repository=context.repository)
        ctx_logger.info(f"Publishing review results ({len(analysis.comments)} comments, "
                       f"summary={'yes' if analysis.summary else 'no'})")
        try:
            if isinstance(context, PullRequestReviewContext):
                ctx_logger.debug(f"Publishing PR review for PR #{context.pull_number}")
                await self._publish_pull_request_review(github_client, context, analysis)
            elif isinstance(context, PushReviewContext):
                ctx_logger.debug(f"Publishing push review for commit {context.after}")
                await self._publish_push_review(github_client, context, analysis)
            else:  # pragma: no cover - defensive branch
                ctx_logger.warning(f"Unsupported review context type: {type(context)}")
            log_success(logger, f"Review results published successfully for {context.repository}",
                       repository=context.repository)
        except GitHubAPIError as exc:
            log_failure(logger, f"Failed to post review comments to GitHub: {exc}", exc, 
                       repository=context.repository)
            # Don't re-raise - publishing failure shouldn't fail the entire job
            # The analysis was successful, just couldn't post comments

    async def _publish_pull_request_review(
        self,
        github_client: GitHubInstallationClient,
        context: PullRequestReviewContext,
        analysis: ReviewAnalysis,
    ) -> None:
        ctx_logger = log_with_context(logger, repository=context.repository)
        
        comments_payload = [
            _build_pr_comment_payload(finding)
            for finding in analysis.comments
            if finding.path and finding.start_line
        ]

        summary_body = _format_summary_body(analysis.summary, analysis.comments)

        if not comments_payload and not summary_body:
            ctx_logger.info(f"Jules produced no actionable comments for PR #{context.pull_number}")
            return

        ctx_logger.info(f"Submitting review for PR #{context.pull_number} with {len(comments_payload)} inline comments")

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
        ctx_logger = log_with_context(logger, repository=context.repository)
        
        target_commit = context.after or (context.commits[-1] if context.commits else None)
        if not target_commit:
            ctx_logger.warning("Push review missing target commit SHA; skipping comment publish")
            return

        comments_posted = 0
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
            comments_posted += 1

        if analysis.summary:
            summary_body = _format_summary_body(analysis.summary, analysis.comments)
            await github_client.create_commit_comment(
                installation_id=context.installation_id,
                full_name=context.repository,
                commit_sha=target_commit,
                body=summary_body,
            )
            comments_posted += 1
        
        ctx_logger.info(f"Posted {comments_posted} comment(s) to commit {target_commit[:8]}")


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

