"""
Lightweight in-process push notification queue.

No Redis, no Celery — asyncio.Queue + a single drain worker.

Why a queue instead of BackgroundTasks.add_task():
  - put_nowait() is O(1) and never blocks the request handler.
  - Transient APNs/FCM failures are retried with exponential backoff
    instead of being silently dropped.
  - Queue depth is observable via .qsize() for health metrics.

Concurrency inside each job is handled by AlertBroadcaster (semaphore-
controlled asyncio.gather over APNs + FCM + SMS), so one drain worker
is sufficient — no parallel workers needed.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from app.services.alert_broadcaster import AlertBroadcaster, BroadcastPlan

logger = logging.getLogger("bluebird.push_queue")

_MAX_RETRIES = 3
_BASE_DELAY_S = 2.0  # doubles each attempt: 2s → 4s → give up


@dataclass
class PushJob:
    broadcaster: "AlertBroadcaster"
    alert_id: int
    message: str
    plan: "BroadcastPlan"
    attempt: int = field(default=0, compare=False)


class PushQueue:
    """
    Async push notification queue.

    Usage:
        queue = PushQueue()
        await queue.start()          # in lifespan
        queue.enqueue(PushJob(...))  # in request handler — non-blocking
        await queue.stop()           # in lifespan teardown
    """

    def __init__(self, maxsize: int = 500) -> None:
        self._queue: asyncio.Queue[PushJob] = asyncio.Queue(maxsize=maxsize)
        self._worker: Optional[asyncio.Task] = None  # type: ignore[type-arg]

    def enqueue(self, job: PushJob) -> bool:
        """
        Non-blocking enqueue.  Returns False (and logs) when the queue is
        full — this is intentional backpressure; better to drop than to OOM.
        """
        try:
            self._queue.put_nowait(job)
            logger.debug(
                "push_queue enqueued alert_id=%s depth=%d",
                job.alert_id, self._queue.qsize(),
            )
            return True
        except asyncio.QueueFull:
            logger.error(
                "push_queue full (maxsize=%d) — dropping alert_id=%s",
                self._queue.maxsize, job.alert_id,
            )
            return False

    def qsize(self) -> int:
        return self._queue.qsize()

    async def start(self) -> None:
        self._worker = asyncio.create_task(self._drain(), name="push-queue-drain")

    async def stop(self) -> None:
        if self._worker:
            self._worker.cancel()
            try:
                await self._worker
            except asyncio.CancelledError:
                pass

    # ── internal ────────────────────────────────────────────────────────────

    async def _drain(self) -> None:
        while True:
            try:
                job = await self._queue.get()
                try:
                    await self._process(job)
                finally:
                    self._queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.exception("push_queue drain error: %s", exc)

    async def _process(self, job: PushJob) -> None:
        try:
            await job.broadcaster.broadcast_panic(
                alert_id=job.alert_id,
                message=job.message,
                plan=job.plan,
            )
        except Exception as exc:
            job.attempt += 1
            if job.attempt < _MAX_RETRIES:
                delay = _BASE_DELAY_S * (2 ** (job.attempt - 1))
                logger.warning(
                    "push_queue retry alert_id=%s attempt=%d in %.1fs: %s",
                    job.alert_id, job.attempt, delay, exc,
                )
                await asyncio.sleep(delay)
                try:
                    self._queue.put_nowait(job)
                except asyncio.QueueFull:
                    logger.error(
                        "push_queue full on retry — dropping alert_id=%s after %d attempts",
                        job.alert_id, job.attempt,
                    )
            else:
                logger.error(
                    "push_queue gave up alert_id=%s after %d attempts: %s",
                    job.alert_id, job.attempt, exc,
                )
