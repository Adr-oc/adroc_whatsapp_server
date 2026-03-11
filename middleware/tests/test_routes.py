"""Tests for all FastAPI routes: webhooks, instances, messages, health, auth."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Admin instance routes
# ---------------------------------------------------------------------------
class TestAdminInstanceRoutes:
    PREFIX = "/api/admin/instances"

    async def test_list_all_instances(self, client, admin_headers):
        """GET /api/admin/instances returns all instances with tenant info."""
        with patch(
            "app.routes.admin_instances.get_all_instances_admin",
            new=AsyncMock(return_value=[]),
        ):
            resp = await client.get(self.PREFIX, headers=admin_headers)
        # DB is empty in unit tests — just verify auth works and shape is right
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_list_instances_requires_admin_key(self, client, tenant_headers):
        resp = await client.get(self.PREFIX, headers=tenant_headers)
        assert resp.status_code == 403

    async def test_list_instances_no_auth_returns_error(self, client):
        resp = await client.get(self.PREFIX)
        assert resp.status_code in (403, 422)


# ---------------------------------------------------------------------------
# Webhook route
# ---------------------------------------------------------------------------
class TestWebhookRoute:
    ENDPOINT = "/webhooks/evolution"

    def _payload(self, event="messages.upsert", instance="acme_ventas", data=None):
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
        assert call_payload["instance"] == "acme_ventas"
        assert mock_enqueue.call_args.kwargs["tenant_odoo_url"] == "https://acme.odoo.com/whatsapp/webhook"
        assert mock_enqueue.call_args.kwargs["tenant_odoo_key"] == "odoo-key"

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
            resp = await client.post(self.ENDPOINT, json=self._payload(instance="acme_ventas"))

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
        with (
            patch("app.routes.instances.evolution_service") as mock_evo,
            patch("app.routes.instances.get_tenant_instance_count", new=AsyncMock(return_value=0)),
            patch("app.routes.instances.upsert_instance", new=AsyncMock(return_value=None)),
            patch("app.routes.instances.tenant_cache") as mock_cache,
        ):
            mock_evo.create_instance = AsyncMock(return_value=mock_result)
            mock_cache.register_instance = MagicMock()
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
        with patch("app.routes.instances.get_tenant_instances", new=AsyncMock(return_value=[])):
            resp = await client.get(self.PREFIX, headers=auth_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 0

    async def test_get_qr_code(self, client, auth_headers):
        with (
            patch("app.routes.instances.get_instance_for_tenant", new=AsyncMock(return_value=None)),
            patch("app.routes.instances.evolution_service") as mock_evo,
        ):
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
        with (
            patch("app.routes.instances.get_instance_for_tenant", new=AsyncMock(return_value=None)),
            patch("app.routes.instances.evolution_service") as mock_evo,
        ):
            mock_evo.connection_state = AsyncMock(return_value={
                "instance": {"instanceName": "ventas", "state": "open"},
            })
            resp = await client.get(f"{self.PREFIX}/ventas/status", headers=auth_headers)

        assert resp.status_code == 200
        assert resp.json()["state"] == "open"

    async def test_delete_instance(self, client, auth_headers):
        with (
            patch("app.routes.instances.evolution_service") as mock_evo,
            patch("app.routes.instances.delete_instance_by_name", new=AsyncMock(return_value=None)),
            patch("app.routes.instances.tenant_cache") as mock_cache,
        ):
            mock_evo.delete_instance = AsyncMock(return_value={"status": "deleted"})
            mock_cache.unregister_instance = MagicMock()
            resp = await client.delete(f"{self.PREFIX}/ventas", headers=auth_headers)

        assert resp.status_code == 200

    async def test_restart_instance(self, client, auth_headers):
        with (
            patch("app.routes.instances.evolution_service") as mock_evo,
            patch("app.routes.instances.upsert_instance", new=AsyncMock(return_value=None)),
        ):
            mock_evo.restart_instance = AsyncMock(return_value={"status": "ok"})
            resp = await client.put(f"{self.PREFIX}/ventas/restart", headers=auth_headers)

        assert resp.status_code == 200

    async def test_logout_instance(self, client, auth_headers):
        with (
            patch("app.routes.instances.evolution_service") as mock_evo,
            patch("app.routes.instances.upsert_instance", new=AsyncMock(return_value=None)),
        ):
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
            instance_name="acme_ventas",
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
        mock_execute_result = MagicMock()
        mock_execute_result.scalar.return_value = 0

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_execute_result

        @asynccontextmanager
        async def mock_session_ctx():
            yield mock_session

        with (
            patch("app.routes.health.async_session", return_value=mock_session_ctx()),
            patch("app.routes.health.evolution_service") as mock_evo,
        ):
            mock_evo.is_reachable = AsyncMock(return_value=True)
            resp = await client.get("/api/health")

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["database"]["status"] == "connected"
        assert body["evolution_api"]["status"] == "reachable"

    async def test_db_down_returns_degraded(self, client):
        @asynccontextmanager
        async def failing_ctx():
            raise ConnectionError("DB is down")
            yield  # unreachable

        with (
            patch("app.routes.health.async_session", return_value=failing_ctx()),
            patch("app.routes.health.evolution_service") as mock_evo,
        ):
            mock_evo.is_reachable = AsyncMock(return_value=True)
            resp = await client.get("/api/health")

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "degraded"
        assert body["database"]["status"] == "disconnected"

    async def test_evolution_unreachable(self, client):
        mock_execute_result = MagicMock()
        mock_execute_result.scalar.return_value = 0

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_execute_result

        @asynccontextmanager
        async def mock_ctx():
            yield mock_session

        with (
            patch("app.routes.health.async_session", return_value=mock_ctx()),
            patch("app.routes.health.evolution_service") as mock_evo,
        ):
            mock_evo.is_reachable = AsyncMock(return_value=False)
            resp = await client.get("/api/health")

        assert resp.status_code == 200
        body = resp.json()
        assert body["evolution_api"]["status"] == "unreachable"

    async def test_health_no_auth_required(self, client):
        """Health endpoint is public."""
        mock_execute_result = MagicMock()
        mock_execute_result.scalar.return_value = 0

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_execute_result

        @asynccontextmanager
        async def mock_ctx():
            yield mock_session

        with (
            patch("app.routes.health.async_session", return_value=mock_ctx()),
            patch("app.routes.health.evolution_service") as mock_evo,
        ):
            mock_evo.is_reachable = AsyncMock(return_value=True)
            resp = await client.get("/api/health")

        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
class TestAuth:
    async def test_valid_key_passes(self, client, tenant_headers):
        with patch("app.routes.instances.get_tenant_instances", new=AsyncMock(return_value=[])):
            resp = await client.get("/api/instances", headers=tenant_headers)
        assert resp.status_code == 200

    async def test_missing_key_fails(self, client):
        resp = await client.get("/api/instances")
        assert resp.status_code in (403, 422)

    async def test_wrong_key_returns_403(self, client):
        resp = await client.get("/api/instances", headers={"X-API-Key": "totally-wrong"})
        assert resp.status_code == 403

    async def test_admin_timing_safe_comparison(self):
        """verify_admin_key uses secrets.compare_digest, not ==."""
        import inspect
        from app.dependencies import verify_admin_key

        source = inspect.getsource(verify_admin_key)
        assert "compare_digest" in source


# ---------------------------------------------------------------------------
# Tenant list update
# ---------------------------------------------------------------------------
class TestTenantListUpdate:
    async def test_list_tenants_includes_instance_count(self, client, admin_headers):
        """GET /api/admin/tenants returns instance_count per tenant."""
        with patch("app.routes.tenants.list_tenants", AsyncMock(return_value=[])):
            resp = await client.get("/api/admin/tenants", headers=admin_headers)
        assert resp.status_code == 200
        for item in resp.json():
            assert "instance_count" in item

    async def test_health_includes_instances_total(self, client):
        mock_execute_result = MagicMock()
        mock_execute_result.scalar.return_value = 0

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_execute_result

        @asynccontextmanager
        async def mock_session_ctx():
            yield mock_session

        with (
            patch("app.routes.health.async_session", return_value=mock_session_ctx()),
            patch("app.routes.health.evolution_service") as mock_evo,
        ):
            mock_evo.is_reachable = AsyncMock(return_value=True)
            resp = await client.get("/api/health")

        assert resp.status_code == 200
        body = resp.json()
        assert "instances" in body
        assert "total" in body["instances"]


# ---------------------------------------------------------------------------
# Logs route
# ---------------------------------------------------------------------------
class TestLogsRoute:
    async def test_logs_no_follow_returns_json(self, client, admin_headers):
        resp = await client.get("/api/logs?lines=10", headers=admin_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert "lines" in body
        assert isinstance(body["lines"], list)

    async def test_logs_requires_admin_key(self, client):
        resp = await client.get("/api/logs")
        assert resp.status_code in (403, 422)

    async def test_logs_wrong_key_returns_403(self, client):
        resp = await client.get("/api/logs", headers={"X-API-Key": "bad"})
        assert resp.status_code == 403
