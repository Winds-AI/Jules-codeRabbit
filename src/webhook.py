"""GitHub webhook ingestion."""

from __future__ import annotations

import json
import time
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import ValidationError

from src.config import Settings, SettingsError
from src.dependencies import settings_dependency
from src.logger import get_logger
from src.queue import enqueue_review_job
from src.queue.models import (
    PullRequestInfo,
    PullRequestPayload,
    PullRequestEndpoint,
    PushPayload,
    RepositoryInfo,
    ReviewJob,
)
from src.utils.security import verify_github_signature

router = APIRouter()

logger = get_logger()

DELIVERY_TTL_SECONDS = 60 * 60  # retain delivery IDs for one hour
_delivery_cache: Dict[str, float] = {}
_supported_pr_actions = {"opened", "reopened", "synchronize", "ready_for_review"}


class IgnoreEventError(RuntimeError):
    """Raised when a webhook event should be acknowledged but not processed."""


def _prune_delivery_cache(now: float) -> None:
    expiry_threshold = now - DELIVERY_TTL_SECONDS
    expired = [key for key, timestamp in _delivery_cache.items() if timestamp < expiry_threshold]
    for key in expired:
        _delivery_cache.pop(key, None)


def _mark_delivery(delivery_id: str, now: float) -> None:
    _delivery_cache[delivery_id] = now


def _is_duplicate(delivery_id: str, now: float) -> bool:
    _prune_delivery_cache(now)
    return delivery_id in _delivery_cache


def _build_push_job(payload: Dict[str, Any]) -> PushPayload:
    installation = payload.get("installation") or {}
    repository = payload.get("repository") or {}

    if not installation.get("id"):
        raise ValueError("Push event missing installation id.")
    if not repository.get("full_name"):
        raise ValueError("Push event missing repository metadata.")

    commits = payload.get("commits") or []
    repo_full_name = repository.get("full_name")
    logger.debug(f"Building PushPayload: repo={repo_full_name}, installation_id={installation.get('id')}, "
                 f"ref={payload.get('ref')}, after={payload.get('after')}, commits={len(commits)}")
    
    return PushPayload(
        installation_id=installation["id"],
        repository=RepositoryInfo(
            id=repository.get("id"),
            full_name=repository.get("full_name"),
            owner=(repository.get("owner") or {}).get("login"),
            name=repository.get("name"),
        ),
        ref=payload.get("ref"),
        before=payload.get("before"),
        after=payload.get("after"),
        commits=[commit.get("id") for commit in commits if commit.get("id")],
        pusher=payload.get("pusher") or {},
        compare=payload.get("compare"),
    )


def _build_pull_request_job(payload: Dict[str, Any]) -> PullRequestPayload:
    action = payload.get("action")
    if action not in _supported_pr_actions:
        raise IgnoreEventError(f"Pull request action '{action}' not actionable.")

    installation = payload.get("installation") or {}
    repository = payload.get("repository") or {}
    pull_request = payload.get("pull_request") or {}

    if not installation.get("id"):
        raise ValueError("Pull request event missing installation id.")
    if not repository.get("full_name"):
        raise ValueError("Pull request event missing repository metadata.")
    if not pull_request.get("number"):
        raise ValueError("Pull request payload missing number.")

    head = pull_request.get("head") or {}
    base = pull_request.get("base") or {}
    repo_full_name = repository.get("full_name")
    pr_number = pull_request.get("number")
    
    logger.debug(f"Building PullRequestPayload: repo={repo_full_name}, PR#{pr_number}, action={action}, "
                 f"installation_id={installation.get('id')}, head_sha={head.get('sha')}, base_sha={base.get('sha')}")

    return PullRequestPayload(
        installation_id=installation["id"],
        repository=RepositoryInfo(
            id=repository.get("id"),
            full_name=repository.get("full_name"),
            owner=(repository.get("owner") or {}).get("login"),
            name=repository.get("name"),
        ),
        action=action,
        pull_request=PullRequestInfo(
            number=pull_request.get("number"),
            title=pull_request.get("title"),
            url=pull_request.get("html_url"),
            head=PullRequestEndpoint(ref=head.get("ref"), sha=head.get("sha")),
            base=PullRequestEndpoint(ref=base.get("ref"), sha=base.get("sha")),
        ),
        sender=payload.get("sender") or {},
    )


def _build_job_payload(event: str, payload: Dict[str, Any]) -> PushPayload | PullRequestPayload:
    if event == "push":
        return _build_push_job(payload)
    if event == "pull_request":
        return _build_pull_request_job(payload)
    raise IgnoreEventError(f"Event '{event}' is not handled.")


@router.post("/webhook", summary="Receive GitHub webhooks")
async def receive_webhook(
    request: Request,
    settings: Settings = Depends(settings_dependency),
) -> Dict[str, str]:
    """Verify webhook signatures, dedupe deliveries, and enqueue review jobs."""

    logger.info("=== WEBHOOK RECEIVED ===")
    
    try:
        credentials = settings.require_code_review_credentials()
        logger.debug("Code review credentials loaded successfully")
    except SettingsError as exc:  # pragma: no cover - guarded by config validation
        logger.error(f"Webhook received but configuration is incomplete: {exc}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    raw_body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256")
    logger.debug(f"Verifying webhook signature (delivery_id: {request.headers.get('X-GitHub-Delivery', 'unknown')})")
    if not verify_github_signature(credentials.github_webhook_secret, raw_body, signature):
        logger.warning("Webhook signature verification failed.")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")

    try:
        payload = json.loads(raw_body.decode("utf-8"))
        logger.debug("Webhook payload parsed successfully")
    except json.JSONDecodeError as exc:
        logger.warning(f"Webhook payload is not valid JSON: {exc}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON payload") from exc

    event = request.headers.get("X-GitHub-Event")
    if not event:
        logger.error("Missing X-GitHub-Event header")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing X-GitHub-Event header")

    delivery_id = request.headers.get("X-GitHub-Delivery")
    if not delivery_id:
        logger.error("Missing X-GitHub-Delivery header")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing X-GitHub-Delivery header")

    logger.info(f"Processing {event} event (delivery_id: {delivery_id})")

    now = time.time()
    if _is_duplicate(delivery_id, now):
        logger.info(f"Duplicate delivery {delivery_id} ignored.")
        return {"status": "ignored", "reason": "duplicate"}

    try:
        logger.debug(f"Building job payload for {event} event")
        job_payload = _build_job_payload(event, payload)
        repo_full_name = getattr(job_payload, "repository", None)
        repo_name = repo_full_name.full_name if repo_full_name else "unknown repository"
        logger.info(f"Job payload built successfully for repository: {repo_name}")
    except IgnoreEventError as exc:
        logger.debug(f"Webhook ignored: {exc}")
        return {"status": "ignored", "reason": str(exc)}
    except ValueError as exc:
        logger.warning(f"Webhook payload rejected: {exc}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    try:
        logger.debug(f"Creating ReviewJob for delivery_id: {delivery_id}")
        job = ReviewJob(delivery_id=delivery_id, event=event, payload=job_payload)
        logger.debug(f"ReviewJob created successfully: delivery_id={job.delivery_id}, event={job.event}")
    except ValidationError as exc:  # pragma: no cover - defensive branch, shouldn't happen
        logger.warning(f"Failed to construct review job: {exc}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid job payload") from exc

    try:
        logger.info(f"Enqueueing review job for delivery_id: {delivery_id}")
        await enqueue_review_job(job)
        logger.info(f"Review job enqueued successfully for delivery_id: {delivery_id}")
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.exception(f"Failed to enqueue review job: {exc}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to enqueue job") from exc

    _mark_delivery(delivery_id, now)
    repo_full_name = getattr(job_payload, "repository", None)
    repo_name = repo_full_name.full_name if repo_full_name else "unknown repository"
    logger.info(f"=== WEBHOOK PROCESSED: Enqueued {event} event for {repo_name} (delivery_id: {delivery_id}) ===")

    return {"status": "accepted"}
