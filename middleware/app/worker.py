"""
Webhook processing worker — Phase 1.

Implements the persist-first architecture:
  webhook arrives → save raw to webhook_events → enqueue event_id →
  worker loads from DB → parses → persists message/contact → forwards to Odoo →
  marks webhook_event processed=True.

Currently the webhook route forwards directly via OdooForwarder (Phase 0).
This module will replace that flow in Phase 1.
"""

import asyncio

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings

log = structlog.get_logger()


class WebhookWorker:
    def __init__(
        self,
        queue: asyncio.Queue,
        db_session_factory: async_sessionmaker[AsyncSession],
        num_workers: int | None = None,
    ) -> None:
        self.queue = queue
        self.db_session_factory = db_session_factory
        self.num_workers = num_workers or settings.ODOO_FORWARD_WORKERS
        self._tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        for i in range(self.num_workers):
            task = asyncio.create_task(
                self._worker(f"webhook-worker-{i}"),
                name=f"webhook-worker-{i}",
            )
            self._tasks.append(task)
        log.info("webhook_workers_started", count=self.num_workers)

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        log.info("webhook_workers_stopped")

    async def _worker(self, name: str) -> None:
        while True:
            try:
                event_id = await self.queue.get()
                await self._process_event(event_id)
            except asyncio.CancelledError:
                break
            except Exception:
                log.exception("webhook_worker_error", worker=name)
            finally:
                self.queue.task_done()

    async def _process_event(self, event_id: int) -> None:
        """Load webhook_event from DB, parse, persist, forward to Odoo.

        Phase 1 implementation will:
        1. Load raw payload from webhook_events by event_id
        2. Parse into typed schema (MessageUpsertData, ConnectionUpdateData, etc.)
        3. Persist to messages/contacts tables
        4. Forward to Odoo via OdooForwarder
        5. Mark webhook_event.processed = True
        6. On error: set webhook_event.processing_error
        """
        raise NotImplementedError("Phase 1: implement _process_event")
