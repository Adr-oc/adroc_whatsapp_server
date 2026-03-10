from contextlib import asynccontextmanager

import logging

import structlog
from fastapi import FastAPI

from app.config import settings
from app.exceptions import (
    EvolutionAPIError,
    OdooForwardError,
    WebhookValidationError,
    evolution_error_handler,
    odoo_forward_error_handler,
    webhook_validation_error_handler,
)
from app.database import async_session
from app.routes import health, instances, messages, resync, tenants, webhooks
from app.services.odoo import odoo_forwarder
from app.services.tenants import tenant_cache

# structlog configuration
shared_processors = [
    structlog.contextvars.merge_contextvars,
    structlog.stdlib.add_log_level,
    structlog.processors.TimeStamper(fmt="iso"),
    structlog.processors.StackInfoRenderer(),
    structlog.processors.format_exc_info,
]

if settings.LOG_FORMAT == "console":
    renderer = structlog.dev.ConsoleRenderer()
else:
    renderer = structlog.processors.JSONRenderer()

log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

structlog.configure(
    processors=[*shared_processors, renderer],
    wrapper_class=structlog.make_filtering_bound_logger(log_level),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

log = structlog.get_logger()


async def _periodic_cache_refresh() -> None:
    """Refresh tenant cache every 60 seconds as a safety net."""
    import asyncio

    while True:
        await asyncio.sleep(60)
        try:
            async with async_session() as db:
                await tenant_cache.refresh(db)
        except Exception as e:
            log.error("cache_refresh_error", error=str(e))


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio

    log.info("startup", workers=settings.ODOO_FORWARD_WORKERS)

    # Initialize tenant cache
    async with async_session() as db:
        await tenant_cache.refresh(db)

    # Start Odoo forwarding workers
    await odoo_forwarder.start()

    # Start periodic cache refresh
    refresh_task = asyncio.create_task(_periodic_cache_refresh())

    yield

    # Graceful shutdown
    refresh_task.cancel()
    log.info("shutdown", pending_tasks=odoo_forwarder.queue.qsize())
    await odoo_forwarder.stop()


app = FastAPI(
    title="adroc_whatsapp middleware",
    version="0.1.0",
    lifespan=lifespan,
)

# Exception handlers
app.add_exception_handler(EvolutionAPIError, evolution_error_handler)
app.add_exception_handler(OdooForwardError, odoo_forward_error_handler)
app.add_exception_handler(WebhookValidationError, webhook_validation_error_handler)

# Routes
app.include_router(health.router)
app.include_router(webhooks.router)
app.include_router(instances.router)
app.include_router(messages.router)
app.include_router(resync.router)
app.include_router(tenants.router)
