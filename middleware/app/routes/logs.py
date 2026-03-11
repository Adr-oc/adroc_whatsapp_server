import asyncio

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app.dependencies import AdminKeyDep
from app.log_buffer import _log_buffer, _LOG_BUFFER_MAX   # import from log_buffer, NOT main
from app.schemas.logs import LogsResponse

router = APIRouter(prefix="/api", dependencies=[AdminKeyDep])


@router.get("/logs", response_model=None)
async def get_logs(
    lines: int = Query(default=100, ge=1, le=_LOG_BUFFER_MAX),
    follow: bool = Query(default=False),
):
    """Stream or snapshot middleware logs.

    - follow=false: returns last `lines` entries as JSON
    - follow=true: SSE stream, flushes history then tails new entries
    """
    if not follow:
        recent = _log_buffer[-lines:] if _log_buffer else []
        return LogsResponse(lines=[line for _, line in recent])

    async def event_stream():
        last_seq = 0
        # Flush history
        recent = _log_buffer[-lines:] if _log_buffer else []
        for seq, line in recent:
            last_seq = max(last_seq, seq)
            yield f"data: {line}\n\n"
        # Tail new entries
        while True:
            new = [(s, l) for s, l in _log_buffer if s > last_seq]
            for seq, line in new:
                last_seq = seq
                yield f"data: {line}\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(event_stream(), media_type="text/event-stream")
