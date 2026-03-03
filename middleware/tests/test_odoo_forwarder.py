"""Tests for OdooForwarder: retry logic, queue management, JSON-RPC wrapping."""

import asyncio
import json

import httpx
import pytest
import respx

from app.config import settings
from app.exceptions import OdooForwardError
from app.services.odoo import OdooForwarder

ODOO_URL = settings.ODOO_WEBHOOK_URL


@pytest.fixture
def forwarder():
    f = OdooForwarder()
    f.queue = asyncio.Queue(maxsize=3)
    yield f


class TestEnqueue:
    async def test_success(self, forwarder):
        await forwarder.enqueue({"event": "test"})
        assert forwarder.queue.qsize() == 1

    async def test_multiple(self, forwarder):
        for i in range(3):
            await forwarder.enqueue({"event": f"test-{i}"})
        assert forwarder.queue.qsize() == 3

    async def test_queue_full_raises(self, forwarder):
        for i in range(3):
            await forwarder.enqueue({"event": f"fill-{i}"})

        with pytest.raises(OdooForwardError, match="queue is full"):
            await forwarder.enqueue({"event": "overflow"})


class TestForwardWithRetry:
    @respx.mock
    async def test_success_first_attempt(self):
        forwarder = OdooForwarder()
        route = respx.post(ODOO_URL).mock(
            return_value=httpx.Response(200, json={"result": "ok"})
        )

        await forwarder._forward_with_retry({"event": "test", "data": {}})

        assert route.call_count == 1

    @respx.mock
    async def test_retries_then_succeeds(self, monkeypatch):
        monkeypatch.setattr(settings, "RETRY_BASE_DELAY", 0.001)
        forwarder = OdooForwarder()

        call_count = 0

        def side_effect(request):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return httpx.Response(500, text="Server Error")
            return httpx.Response(200, json={"result": "ok"})

        respx.post(ODOO_URL).mock(side_effect=side_effect)
        await forwarder._forward_with_retry({"event": "test"})

        assert call_count == 3

    @respx.mock
    async def test_exhausts_retries_raises(self, monkeypatch):
        monkeypatch.setattr(settings, "RETRY_BASE_DELAY", 0.001)
        monkeypatch.setattr(settings, "RETRY_MAX_ATTEMPTS", 2)
        forwarder = OdooForwarder()

        respx.post(ODOO_URL).mock(
            return_value=httpx.Response(502, text="Bad Gateway")
        )

        with pytest.raises(OdooForwardError, match="Failed after 2 attempts"):
            await forwarder._forward_with_retry({"event": "test"})

    @respx.mock
    async def test_connection_error_retries(self, monkeypatch):
        monkeypatch.setattr(settings, "RETRY_BASE_DELAY", 0.001)
        monkeypatch.setattr(settings, "RETRY_MAX_ATTEMPTS", 2)
        forwarder = OdooForwarder()

        respx.post(ODOO_URL).mock(side_effect=httpx.ConnectError("Connection refused"))

        with pytest.raises(OdooForwardError):
            await forwarder._forward_with_retry({"event": "test"})


class TestJsonRpcWrapping:
    @respx.mock
    async def test_payload_wrapped_in_jsonrpc(self):
        forwarder = OdooForwarder()
        route = respx.post(ODOO_URL).mock(
            return_value=httpx.Response(200, json={"result": "ok"})
        )

        payload = {"event": "messages.upsert", "instance": "ventas", "data": {"key": "val"}}
        await forwarder._forward_with_retry(payload)

        sent = json.loads(route.calls[0].request.content)
        assert sent["jsonrpc"] == "2.0"
        assert sent["id"] == 1
        assert sent["method"] == "call"
        assert sent["params"] == payload

    @respx.mock
    async def test_headers_include_api_key(self):
        forwarder = OdooForwarder()
        route = respx.post(ODOO_URL).mock(
            return_value=httpx.Response(200, json={"result": "ok"})
        )

        await forwarder._forward_with_retry({"event": "test"})

        request = route.calls[0].request
        assert request.headers["X-API-Key"] == settings.ODOO_API_KEY
        assert request.headers["Content-Type"] == "application/json"


class TestWorkerLifecycle:
    async def test_start_and_stop(self):
        forwarder = OdooForwarder()
        await forwarder.start()
        assert len(forwarder._workers) == settings.ODOO_FORWARD_WORKERS
        assert all(not t.done() for t in forwarder._workers)

        await forwarder.stop()
        assert len(forwarder._workers) == 0
