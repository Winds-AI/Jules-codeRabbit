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
    logger.debug(f"Building review context for {job.event} event (delivery_id: {job.delivery_id})")

    if isinstance(payload, PushPayload):
        if not payload.after:
            raise ValueError("Push payload missing 'after' commit sha.")
        if not payload.repository.full_name:
            raise ValueError("Push payload missing repository full name.")

        logger.info(f"Fetching commit compare for push: repo={payload.repository.full_name}, "
                   f"base={payload.before or payload.after}, head={payload.after}")
        compare = await client.get_commit_compare(
            installation_id=payload.installation_id,
            full_name=payload.repository.full_name,
            base=payload.before or payload.after,
            head=payload.after,
        )
        logger.debug(f"Commit compare fetched: {len(compare.get('files', []))} files changed")
        files = _serialize_files(compare.get("files", []))
        logger.info(f"PushReviewContext created: repo={payload.repository.full_name}, "
                   f"files={len(files)}, commits={len(payload.commits)}")
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

        logger.info(f"Fetching PR files: repo={payload.repository.full_name}, PR#{pr_info.number}")
        files = await client.list_pull_request_files(
            installation_id=payload.installation_id,
            full_name=payload.repository.full_name,
            pull_number=pr_info.number,
        )
        logger.debug(f"PR files fetched: {len(files)} files")
        serialized_files = _serialize_files(files)
        logger.info(f"PullRequestReviewContext created: repo={payload.repository.full_name}, "
                   f"PR#{pr_info.number}, files={len(serialized_files)}, "
                   f"head_sha={pr_info.head.sha[:8]}, base_sha={pr_info.base.sha[:8]}")
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

