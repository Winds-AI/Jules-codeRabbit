"""In-memory queue for asynchronous review job processing."""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from src.logger import get_logger

from .models import PullRequestPayload, PushPayload, ReviewJob

logger = get_logger()

ReviewJobHandler = Callable[[ReviewJob], Awaitable[None]]


class _ReviewQueue:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[ReviewJob] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None
        self._handler: ReviewJobHandler | None = None

    def configure_handler(self, handler: ReviewJobHandler | None) -> None:
        self._handler = handler

    def _ensure_worker(self) -> None:
        if self._worker is None or self._worker.done():
            loop = asyncio.get_running_loop()
            self._worker = loop.create_task(self._worker_loop())

    async def _worker_loop(self) -> None:
        while True:
            job = await self._queue.get()
            logger.info(f"=== QUEUE: Dequeued job for processing (delivery_id: {job.delivery_id}, event: {job.event}) ===")
            try:
                if self._handler is None:
                    logger.warning(
                        f"No review job handler configured; dropping delivery {job.delivery_id}."
                    )
                else:
                    logger.debug(f"Invoking review handler for delivery_id: {job.delivery_id}")
                    await self._handler(job)
                    logger.info(f"=== QUEUE: Job processing completed successfully (delivery_id: {job.delivery_id}) ===")
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.exception(f"=== QUEUE: Unhandled exception while processing job {job.delivery_id}: {exc} ===")
            finally:
                self._queue.task_done()

    async def enqueue(self, job: ReviewJob) -> None:
        self._ensure_worker()
        await self._queue.put(job)

    async def shutdown(self) -> None:
        if self._worker is None:
            return
        self._worker.cancel()
        try:
            await self._worker
        except asyncio.CancelledError:  # pragma: no cover - expected during shutdown
            pass
        finally:
            self._worker = None

    def pending(self) -> int:
        return self._queue.qsize()


_QUEUE = _ReviewQueue()


def _coerce_job(job: ReviewJob | dict[str, Any]) -> ReviewJob:
    if isinstance(job, ReviewJob):
        return job
    payload = job.get("payload")
    if isinstance(payload, dict):
        event = job.get("event")
        if event == "push":
            job["payload"] = PushPayload.model_validate(payload)
        elif event == "pull_request":
            job["payload"] = PullRequestPayload.model_validate(payload)
    return ReviewJob.model_validate(job)


async def enqueue_review_job(job: ReviewJob | dict[str, Any]) -> None:
    """Add a job to the in-memory queue, starting the worker if needed."""

    review_job = _coerce_job(job)
    logger.debug(f"Adding job to queue: delivery_id={review_job.delivery_id}, event={review_job.event}, "
                 f"pending_jobs={_QUEUE.pending()}")
    await _QUEUE.enqueue(review_job)
    logger.debug(f"Job added to queue: delivery_id={review_job.delivery_id}, new_pending_jobs={_QUEUE.pending()}")


def configure_review_handler(handler: ReviewJobHandler | None) -> None:
    """Configure the coroutine that processes jobs from the queue."""

    _QUEUE.configure_handler(handler)


async def shutdown_queue() -> None:
    """Gracefully stop the worker task."""

    await _QUEUE.shutdown()


def pending_jobs() -> int:
    """Return the number of jobs waiting in the queue."""

    return _QUEUE.pending()

