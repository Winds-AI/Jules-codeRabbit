"""Helpers to build review context from GitHub webhook jobs."""

from __future__ import annotations

from typing import List

from src.github_client import GitHubInstallationClient
from src.logger import get_logger
from src.models.review import FilePatch, PullRequestReviewContext, PushReviewContext, ReviewContext
from src.queue.models import PullRequestPayload, PushPayload, ReviewJob

logger = get_logger()


def _serialize_files(files: List[dict]) -> List[FilePatch]:
    serialized: List[FilePatch] = []
    for file in files:
        # GitHub API may return "filename" or "path" depending on endpoint
        path = file.get("filename") or file.get("path")
        if not path:
            logger.warning(f"Skipping file entry missing filename/path: {file}")
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
    return serialized


async def build_review_context(
    client: GitHubInstallationClient, job: ReviewJob
) -> ReviewContext:
    payload = job.payload

    if isinstance(payload, PushPayload):
        if not payload.after:
            raise ValueError("Push payload missing 'after' commit sha.")
        if not payload.repository.full_name:
            raise ValueError("Push payload missing repository full name.")

        compare = await client.get_commit_compare(
            installation_id=payload.installation_id,
            full_name=payload.repository.full_name,
            base=payload.before or payload.after,
            head=payload.after,
        )
        files = _serialize_files(compare.get("files", []))
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
            raise ValueError("Pull request payload missing repository full name.")
        pr_info = payload.pull_request

        files = await client.list_pull_request_files(
            installation_id=payload.installation_id,
            full_name=payload.repository.full_name,
            pull_number=pr_info.number,
        )
        return PullRequestReviewContext(
            repository=payload.repository.full_name,
            installation_id=payload.installation_id,
            pull_number=pr_info.number,
            title=pr_info.title,
            head_sha=pr_info.head.sha,
            base_sha=pr_info.base.sha,
            files=_serialize_files(files),
            url=pr_info.url,
        )

    raise TypeError(f"Unsupported payload type: {type(payload)!r}")

