import asyncio
from typing import Any

import httpx
import structlog

from app.config import settings
from app.exceptions import OdooForwardError

log = structlog.get_logger()


class OdooForwarder:
    """Bounded-concurrency Odoo forwarder using asyncio.Queue + workers."""

    def __init__(self) -> None:
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(
            maxsize=settings.ODOO_FORWARD_QUEUE_SIZE
        )
        self._workers: list[asyncio.Task] = []
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=30.0,
                limits=httpx.Limits(max_connections=settings.ODOO_FORWARD_WORKERS),
            )
        return self._client

    async def start(self) -> None:
        for i in range(settings.ODOO_FORWARD_WORKERS):
            task = asyncio.create_task(self._worker(i), name=f"odoo-worker-{i}")
            self._workers.append(task)
        log.info("odoo_forwarder_started", workers=len(self._workers))

    async def stop(self) -> None:
        # Signal workers to stop
        for _ in self._workers:
            await self.queue.put({"_stop": True})

        # Wait for workers to finish
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()

        if self._client and not self._client.is_closed:
            await self._client.aclose()
        log.info("odoo_forwarder_stopped")

    async def enqueue(self, payload: dict[str, Any]) -> None:
        try:
            self.queue.put_nowait(payload)
        except asyncio.QueueFull:
            log.error("odoo_queue_full", queue_size=self.queue.qsize())
            raise OdooForwardError("Odoo forwarding queue is full")

    async def _worker(self, worker_id: int) -> None:
        log.debug("odoo_worker_started", worker_id=worker_id)
        while True:
            payload = await self.queue.get()
            try:
                if payload.get("_stop"):
                    break
                await self._forward_with_retry(payload)
            except Exception:
                log.exception("odoo_worker_error", worker_id=worker_id)
            finally:
                self.queue.task_done()

    async def _forward_with_retry(self, payload: dict[str, Any]) -> None:
        """Forward payload to Odoo with exponential backoff retry."""
        last_error: Exception | None = None

        for attempt in range(settings.RETRY_MAX_ATTEMPTS):
            try:
                response = await self.client.post(
                    settings.ODOO_WEBHOOK_URL,
                    json=payload,
                    headers={
                        "X-API-Key": settings.ODOO_API_KEY,
                        "Content-Type": "application/json",
                    },
                )
                response.raise_for_status()
                log.debug("odoo_forward_success", attempt=attempt + 1)
                return
            except (httpx.HTTPStatusError, httpx.RequestError) as e:
                last_error = e
                delay = settings.RETRY_BASE_DELAY * (2**attempt)
                log.warning(
                    "odoo_forward_retry",
                    attempt=attempt + 1,
                    max_attempts=settings.RETRY_MAX_ATTEMPTS,
                    delay=delay,
                    error=str(e),
                )
                await asyncio.sleep(delay)

        raise OdooForwardError(
            f"Failed after {settings.RETRY_MAX_ATTEMPTS} attempts: {last_error}"
        )

    async def is_reachable(self) -> bool:
        try:
            response = await self.client.head(
                settings.ODOO_WEBHOOK_URL,
                headers={"X-API-Key": settings.ODOO_API_KEY},
            )
            return response.status_code < 500
        except Exception:
            return False


odoo_forwarder = OdooForwarder()
