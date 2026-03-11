"""Shared in-memory log buffer for /api/logs endpoint.

Kept in its own module to avoid circular imports between main.py and routes/logs.py.
"""
import json

_log_seq: int = 0
_log_buffer: list[tuple[int, str]] = []   # (seq, json_str), append-only, capped at 1000
_LOG_BUFFER_MAX = 1000


def buffer_log_processor(logger, method, event_dict: dict) -> dict:
    """Structlog processor: capture each log entry into the in-memory ring buffer."""
    global _log_seq
    _log_seq += 1
    _log_buffer.append((_log_seq, json.dumps(event_dict, default=str)))
    if len(_log_buffer) > _LOG_BUFFER_MAX:
        del _log_buffer[:-_LOG_BUFFER_MAX]
    return event_dict   # pass through unchanged
