"""Tests for all FastAPI routes: webhooks, instances, messages, health, auth."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Webhook route
# ---------------------------------------------------------------------------
class TestWebhookRoute:
    ENDPOINT = "/webhooks/evolution"

    def _payload(self, event="messages.upsert", instance="ventas", data=None):
        return {
            "event": event,
            "instance": instance,
            "data": data or {"key": {"remoteJid": "502xxx@s.whatsapp.net", "fromMe": False, "id": "abc"}},
        }

    async def test_forward_event_enqueues_and_returns_200(self, client):
        mock_enqueue = AsyncMock()
        with patch("app.routes.webhooks.odoo_forwarder") as mock_fwd:
            mock_fwd.enqueue = mock_enqueue
            resp = await client.post(self.ENDPOINT, json=self._payload())

        assert resp.status_code == 200
        assert resp.json() == {"status": "received"}
        mock_enqueue.assert_called_once()
        call_payload = mock_enqueue.call_args[0][0]
        assert call_payload["event"] == "messages.upsert"
        assert call_payload["instance"] == "ventas"

    async def test_non_forward_event_skips_enqueue(self, client):
        mock_enqueue = AsyncMock()
        with patch("app.routes.webhooks.odoo_forwarder") as mock_fwd:
            mock_fwd.enqueue = mock_enqueue
            resp = await client.post(
                self.ENDPOINT,
                json=self._payload(event="some.unknown.event"),
            )

        assert resp.status_code == 200
        mock_enqueue.assert_not_called()

    async def test_all_forward_events_accepted(self, client):
        from app.routes.webhooks import FORWARD_EVENTS

        for event in FORWARD_EVENTS:
            mock_enqueue = AsyncMock()
            with patch("app.routes.webhooks.odoo_forwarder") as mock_fwd:
                mock_fwd.enqueue = mock_enqueue
                resp = await client.post(
                    self.ENDPOINT,
                    json=self._payload(event=event),
                )
            assert resp.status_code == 200, f"Failed for event: {event}"

    async def test_queue_full_returns_503(self, client):
        from app.exceptions import OdooForwardError

        mock_fwd = MagicMock()
        mock_fwd.enqueue = AsyncMock(side_effect=OdooForwardError("queue is full"))
        mock_fwd.queue.qsize.return_value = 1000

        with patch("app.routes.webhooks.odoo_forwarder", mock_fwd):
            resp = await client.post(self.ENDPOINT, json=self._payload())

        assert resp.status_code == 503
        assert "capacity" in resp.json()["detail"]

    async def test_invalid_payload_returns_422(self, client):
        resp = await client.post(self.ENDPOINT, json={"bad": "data"})
        assert resp.status_code == 422

    async def test_list_data_rejected(self, client):
        resp = await client.post(
            self.ENDPOINT,
            json={"event": "messages.upsert", "instance": "ventas", "data": [1, 2, 3]},
        )
        assert resp.status_code == 422

    async def test_no_auth_required(self, client):
        """Webhook endpoint doesn't require X-API-Key."""
        mock_enqueue = AsyncMock()
        with patch("app.routes.webhooks.odoo_forwarder") as mock_fwd:
            mock_fwd.enqueue = mock_enqueue
            resp = await client.post(self.ENDPOINT, json=self._payload())
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Instance routes
# ---------------------------------------------------------------------------
class TestInstanceRoutes:
    PREFIX = "/api/instances"

    async def test_create_instance(self, client, auth_headers):
        mock_result = {
            "instance": {"instanceName": "ventas", "instanceId": "uuid-123"},
            "hash": {"apikey": "tok"},
            "qrcode": {"base64": "data:image/png;base64,abc"},
        }
        with patch("app.routes.instances.evolution_service") as mock_evo:
            mock_evo.create_instance = AsyncMock(return_value=mock_result)
            resp = await client.post(
                self.PREFIX,
                json={"instance_name": "ventas"},
                headers=auth_headers,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["instance_name"] == "ventas"
        assert body["state"] == "created"
        assert body["qrcode_base64"] == "data:image/png;base64,abc"

    async def test_list_instances(self, client, auth_headers):
        with patch("app.routes.instances.evolution_service") as mock_evo:
            mock_evo.fetch_instances = AsyncMock(return_value=[
                {"name": "ventas", "connectionStatus": "open"},
                {"name": "soporte", "connectionStatus": "close"},
            ])
            resp = await client.get(self.PREFIX, headers=auth_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["instance_name"] == "ventas"
        assert data[0]["state"] == "open"

    async def test_get_qr_code(self, client, auth_headers):
        with patch("app.routes.instances.evolution_service") as mock_evo:
            mock_evo.connect = AsyncMock(return_value={
                "base64": "data:image/png;base64,qr123",
                "code": "2@AbCdEf",
            })
            resp = await client.get(f"{self.PREFIX}/ventas/qr", headers=auth_headers)

        assert resp.status_code == 200
        body = resp.json()
        assert body["base64"] == "data:image/png;base64,qr123"
        assert body["code"] == "2@AbCdEf"

    async def test_get_status(self, client, auth_headers):
        with patch("app.routes.instances.evolution_service") as mock_evo:
            mock_evo.connection_state = AsyncMock(return_value={
                "instance": {"instanceName": "ventas", "state": "open"},
            })
            resp = await client.get(f"{self.PREFIX}/ventas/status", headers=auth_headers)

        assert resp.status_code == 200
        assert resp.json()["state"] == "open"

    async def test_delete_instance(self, client, auth_headers):
        with patch("app.routes.instances.evolution_service") as mock_evo:
            mock_evo.delete_instance = AsyncMock(return_value={"status": "deleted"})
            resp = await client.delete(f"{self.PREFIX}/ventas", headers=auth_headers)

        assert resp.status_code == 200

    async def test_restart_instance(self, client, auth_headers):
        with patch("app.routes.instances.evolution_service") as mock_evo:
            mock_evo.restart_instance = AsyncMock(return_value={"status": "ok"})
            resp = await client.put(f"{self.PREFIX}/ventas/restart", headers=auth_headers)

        assert resp.status_code == 200

    async def test_logout_instance(self, client, auth_headers):
        with patch("app.routes.instances.evolution_service") as mock_evo:
            mock_evo.logout_instance = AsyncMock(return_value={"status": "ok"})
            resp = await client.delete(f"{self.PREFIX}/ventas/logout", headers=auth_headers)

        assert resp.status_code == 200

    async def test_no_api_key_returns_error(self, client):
        resp = await client.get(self.PREFIX)
        assert resp.status_code in (403, 422)

    async def test_wrong_api_key_returns_403(self, client):
        resp = await client.get(self.PREFIX, headers={"X-API-Key": "wrong-key"})
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Message routes
# ---------------------------------------------------------------------------
class TestMessageRoutes:
    async def test_send_text(self, client, auth_headers):
        with patch("app.routes.messages.evolution_service") as mock_evo:
            mock_evo.send_text = AsyncMock(return_value={
                "key": {"remoteJid": "502xxx@s.whatsapp.net", "fromMe": True, "id": "BAE594"},
                "status": "PENDING",
            })
            resp = await client.post(
                "/api/instances/ventas/send",
                json={"number": "502xxx", "text": "Hello!"},
                headers=auth_headers,
            )

        assert resp.status_code == 200
        assert resp.json()["key"]["fromMe"] is True
        mock_evo.send_text.assert_called_once_with(
            instance_name="ventas",
            number="502xxx",
            text="Hello!",
            quoted=None,
        )

    async def test_send_media_url(self, client, auth_headers):
        with patch("app.routes.messages.evolution_service") as mock_evo:
            mock_evo.send_media = AsyncMock(return_value={"key": {"id": "media-1"}})
            resp = await client.post(
                "/api/instances/ventas/send",
                json={
                    "number": "502xxx",
                    "text": "Check this",
                    "media_url": "https://example.com/photo.jpg",
                    "media_type": "image",
                },
                headers=auth_headers,
            )

        assert resp.status_code == 200
        mock_evo.send_media.assert_called_once()

    async def test_send_requires_auth(self, client):
        resp = await client.post(
            "/api/instances/ventas/send",
            json={"number": "502xxx", "text": "Hello!"},
        )
        assert resp.status_code in (403, 422)


# ---------------------------------------------------------------------------
# Health route
# ---------------------------------------------------------------------------
class TestHealthRoute:
    async def test_all_healthy(self, client):
        mock_session = MagicMock()
        mock_session_instance = AsyncMock()
        mock_session_instance.execute = AsyncMock()

        @asynccontextmanager
        async def mock_ctx():
            yield mock_session_instance

        mock_session.side_effect = lambda: mock_ctx()
        mock_session.return_value = mock_ctx()

        with (
            patch("app.routes.health.async_session", mock_session),
            patch("app.routes.health.evolution_service") as mock_evo,
        ):
            mock_evo.is_reachable = AsyncMock(return_value=True)
            # async_session is used as `async with async_session() as session:`
            # Need to make it return an async context manager
            resp = await client.get("/api/health")

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["database"] == "connected"
        assert body["evolution_api"] == "reachable"

    async def test_db_down_returns_degraded(self, client):
        @asynccontextmanager
        async def failing_session():
            raise ConnectionError("DB is down")
            yield  # noqa: unreachable

        with (
            patch("app.routes.health.async_session", return_value=failing_session()),
            patch("app.routes.health.evolution_service") as mock_evo,
        ):
            mock_evo.is_reachable = AsyncMock(return_value=True)
            resp = await client.get("/api/health")

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "degraded"
        assert body["database"] == "disconnected"

    async def test_evolution_unreachable(self, client):
        mock_session_instance = AsyncMock()
        mock_session_instance.execute = AsyncMock()

        @asynccontextmanager
        async def mock_ctx():
            yield mock_session_instance

        with (
            patch("app.routes.health.async_session", return_value=mock_ctx()),
            patch("app.routes.health.evolution_service") as mock_evo,
        ):
            mock_evo.is_reachable = AsyncMock(return_value=False)
            resp = await client.get("/api/health")

        assert resp.status_code == 200
        body = resp.json()
        assert body["evolution_api"] == "unreachable"

    async def test_health_no_auth_required(self, client):
        """Health endpoint is public."""
        with (
            patch("app.routes.health.async_session") as mock_sess,
            patch("app.routes.health.evolution_service") as mock_evo,
        ):
            mock_evo.is_reachable = AsyncMock(return_value=True)

            @asynccontextmanager
            async def mock_ctx():
                mock_s = AsyncMock()
                mock_s.execute = AsyncMock()
                yield mock_s

            mock_sess.return_value = mock_ctx()
            resp = await client.get("/api/health")

        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
class TestAuth:
    async def test_valid_key_passes(self, client, auth_headers):
        with patch("app.routes.instances.evolution_service") as mock_evo:
            mock_evo.fetch_instances = AsyncMock(return_value=[])
            resp = await client.get("/api/instances", headers=auth_headers)
        assert resp.status_code == 200

    async def test_missing_key_fails(self, client):
        resp = await client.get("/api/instances")
        assert resp.status_code in (403, 422)

    async def test_wrong_key_returns_403(self, client):
        resp = await client.get("/api/instances", headers={"X-API-Key": "totally-wrong"})
        assert resp.status_code == 403

    async def test_timing_safe_comparison(self):
        """Verify we use secrets.compare_digest, not ==."""
        import inspect
        from app.dependencies import verify_api_key

        source = inspect.getsource(verify_api_key)
        assert "compare_digest" in source
        assert "==" not in source or "status_code" in source
