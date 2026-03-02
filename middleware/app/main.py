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
from app.routes import health, instances, messages, resync, webhooks
from app.services.odoo import odoo_forwarder

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("startup", workers=settings.ODOO_FORWARD_WORKERS)

    # Start Odoo forwarding workers
    await odoo_forwarder.start()

    yield

    # Graceful shutdown: drain the queue
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
