"""Helpers to build review context from GitHub webhook jobs."""

from __future__ import annotations

from typing import List

from src.github_client import GitHubInstallationClient, GitHubAPIError
from src.logger import get_logger, log_with_context, log_timing
from src.models.review import FilePatch, PullRequestReviewContext, PushReviewContext, ReviewContext
from src.queue.models import PullRequestPayload, PushPayload, ReviewJob

logger = get_logger()


def _serialize_files(files: List[dict]) -> List[FilePatch]:
    serialized: List[FilePatch] = []
    skipped_count = 0
    for file in files:
        # GitHub API may return "filename" or "path" depending on endpoint
        path = file.get("filename") or file.get("path")
        if not path:
            logger.warning(f"Skipping file entry missing filename/path: {file}")
            skipped_count += 1
            continue
        serialized.append(
            FilePatch(
                path=path,
                status=file.get("status", ""),
                additions=int(file.get("additions", 0) or 0),
                deletions=int(file.get("deletions", 0) or 0),
                patch=file.get("patch"),
            )
        )
    if skipped_count > 0:
        logger.warning(f"Skipped {skipped_count} file(s) due to missing path/filename")
    logger.debug(f"Serialized {len(serialized)} file(s) from {len(files)} file entries")
    return serialized


async def build_review_context(
    client: GitHubInstallationClient, job: ReviewJob
) -> ReviewContext:
    payload = job.payload
    
    # Extract repository name for context
    repo_name = "unknown"
    if hasattr(payload, "repository") and payload.repository:
        repo_name = getattr(payload.repository, "full_name", "unknown")
    
    ctx_logger = log_with_context(logger, 
                                  delivery_id=job.delivery_id, 
                                  event_type=job.event,
                                  repository=repo_name)
    
    ctx_logger.debug(f"Building review context for {job.event} event")

    if isinstance(payload, PushPayload):
        if not payload.after:
            raise ValueError("Push payload missing 'after' commit sha")
        if not payload.repository.full_name:
            raise ValueError("Push payload missing repository full name")

        base_sha = payload.before or payload.after
        head_sha = payload.after
        ctx_logger.info(f"Fetching commit compare: base={base_sha[:8] if base_sha else 'none'}, "
                       f"head={head_sha[:8] if head_sha else 'none'}")
        
        try:
            with log_timing(ctx_logger, "fetch_commit_compare"):
                compare = await client.get_commit_compare(
                    installation_id=payload.installation_id,
                    full_name=payload.repository.full_name,
                    base=base_sha,
                    head=head_sha,
                )
        except GitHubAPIError as exc:
            # Categorize GitHub API errors
            if exc.status_code == 404:
                ctx_logger.error(f"Repository or commits not found (404): {exc}")
                raise
            elif exc.status_code == 403:
                ctx_logger.error(f"Permission denied (403): {exc}")
                raise
            elif exc.status_code == 429:
                ctx_logger.error(f"Rate limit exceeded (429): {exc}")
                raise
            else:
                ctx_logger.error(f"GitHub API error ({exc.status_code}): {exc}")
                raise
        
        files_data = compare.get("files", [])
        ctx_logger.debug(f"Commit compare fetched: {len(files_data)} files changed")
        files = _serialize_files(files_data)
        
        if len(files) == 0:
            ctx_logger.warning("No files changed in this push")
        
        ctx_logger.info(f"PushReviewContext created: files={len(files)}, commits={len(payload.commits)}")
        return PushReviewContext(
            repository=payload.repository.full_name,
            installation_id=payload.installation_id,
            ref=payload.ref,
            before=payload.before,
            after=payload.after,
            commits=list(payload.commits),
            files=files,
            compare_url=compare.get("html_url") or payload.compare,
        )

    if isinstance(payload, PullRequestPayload):
        if not payload.repository.full_name:
            raise ValueError("Pull request payload missing repository full name")
        pr_info = payload.pull_request

        ctx_logger.info(f"Fetching PR files: PR#{pr_info.number}, "
                       f"head={pr_info.head.sha[:8] if pr_info.head.sha else 'none'}, "
                       f"base={pr_info.base.sha[:8] if pr_info.base.sha else 'none'}")
        
        try:
            with log_timing(ctx_logger, "fetch_pr_files"):
                files = await client.list_pull_request_files(
                    installation_id=payload.installation_id,
                    full_name=payload.repository.full_name,
                    pull_number=pr_info.number,
                )
        except GitHubAPIError as exc:
            # Categorize GitHub API errors
            if exc.status_code == 404:
                ctx_logger.error(f"PR or repository not found (404): {exc}")
                raise
            elif exc.status_code == 403:
                ctx_logger.error(f"Permission denied (403): {exc}")
                raise
            elif exc.status_code == 429:
                ctx_logger.error(f"Rate limit exceeded (429): {exc}")
                raise
            else:
                ctx_logger.error(f"GitHub API error ({exc.status_code}): {exc}")
                raise
        
        ctx_logger.debug(f"PR files fetched: {len(files)} files")
        serialized_files = _serialize_files(files)
        
        if len(serialized_files) == 0:
            ctx_logger.warning(f"No files changed in PR #{pr_info.number}")
        
        ctx_logger.info(f"PullRequestReviewContext created: PR#{pr_info.number}, files={len(serialized_files)}")
        return PullRequestReviewContext(
            repository=payload.repository.full_name,
            installation_id=payload.installation_id,
            pull_number=pr_info.number,
            title=pr_info.title,
            head_sha=pr_info.head.sha,
            base_sha=pr_info.base.sha,
            head_ref=pr_info.head.ref,
            files=serialized_files,
            url=pr_info.url,
        )

    raise TypeError(f"Unsupported payload type: {type(payload)!r}")

