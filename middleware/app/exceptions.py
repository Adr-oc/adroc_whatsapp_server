import structlog
from fastapi import Request
from fastapi.responses import JSONResponse

log = structlog.get_logger()


class EvolutionAPIError(Exception):
    """Error communicating with Evolution API."""

    def __init__(self, message: str, status_code: int | None = None):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class OdooForwardError(Exception):
    """Error forwarding data to Odoo."""

    def __init__(self, message: str, status_code: int | None = None):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class WebhookValidationError(Exception):
    """Invalid webhook payload from Evolution."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


async def evolution_error_handler(request: Request, exc: EvolutionAPIError) -> JSONResponse:
    log.error("evolution_api_error", error=exc.message, status_code=exc.status_code)
    return JSONResponse(
        status_code=502,
        content={"detail": f"Evolution API error: {exc.message}"},
    )


async def odoo_forward_error_handler(request: Request, exc: OdooForwardError) -> JSONResponse:
    log.error("odoo_forward_error", error=exc.message, status_code=exc.status_code)
    return JSONResponse(
        status_code=502,
        content={"detail": f"Odoo forwarding error: {exc.message}"},
    )


async def webhook_validation_error_handler(
    request: Request, exc: WebhookValidationError
) -> JSONResponse:
    log.warning("webhook_validation_error", error=exc.message)
    return JSONResponse(
        status_code=422,
        content={"detail": f"Webhook validation error: {exc.message}"},
    )
