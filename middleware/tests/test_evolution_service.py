"""Tests for EvolutionService: API calls, error handling."""

import httpx
import pytest
import respx

from app.config import settings
from app.exceptions import EvolutionAPIError
from app.services.evolution import EvolutionService

BASE = settings.EVOLUTION_API_URL


class TestEvolutionRequests:
    @respx.mock
    async def test_create_instance(self):
        svc = EvolutionService()
        respx.post(f"{BASE}/instance/create").mock(
            return_value=httpx.Response(200, json={
                "instance": {"instanceName": "ventas", "instanceId": "uuid-123", "status": "created"},
                "hash": {"apikey": "token-abc"},
                "qrcode": {"base64": "data:image/png;base64,abc"},
            })
        )

        result = await svc.create_instance("ventas")

        assert result["instance"]["instanceName"] == "ventas"
        assert result["hash"]["apikey"] == "token-abc"

    @respx.mock
    async def test_fetch_instances(self):
        svc = EvolutionService()
        respx.get(f"{BASE}/instance/fetchInstances").mock(
            return_value=httpx.Response(200, json=[
                {"name": "ventas", "connectionStatus": "open"},
                {"name": "soporte", "connectionStatus": "close"},
            ])
        )

        result = await svc.fetch_instances()

        assert len(result) == 2
        assert result[0]["name"] == "ventas"

    @respx.mock
    async def test_connection_state(self):
        svc = EvolutionService()
        respx.get(f"{BASE}/instance/connectionState/ventas").mock(
            return_value=httpx.Response(200, json={
                "instance": {"instanceName": "ventas", "state": "open"},
            })
        )

        result = await svc.connection_state("ventas")

        assert result["instance"]["state"] == "open"

    @respx.mock
    async def test_send_text(self):
        svc = EvolutionService()
        respx.post(f"{BASE}/message/sendText/ventas").mock(
            return_value=httpx.Response(200, json={
                "key": {"remoteJid": "502xxx@s.whatsapp.net", "fromMe": True, "id": "BAE594"},
                "status": "PENDING",
            })
        )

        result = await svc.send_text("ventas", "502xxx", "Hello!")

        assert result["key"]["fromMe"] is True
        import json
        sent_body = json.loads(respx.calls[0].request.content)
        assert sent_body["number"] == "502xxx"
        assert sent_body["text"] == "Hello!"
        assert sent_body["delay"] == 1200
        assert sent_body["presence"] == "composing"

    @respx.mock
    async def test_send_media(self):
        svc = EvolutionService()
        respx.post(f"{BASE}/message/sendMedia/ventas").mock(
            return_value=httpx.Response(200, json={"key": {"id": "media-123"}})
        )

        result = await svc.send_media(
            "ventas", "502xxx", "https://example.com/image.jpg",
            media_type="image", caption="Check this",
        )

        assert result["key"]["id"] == "media-123"

    @respx.mock
    async def test_delete_instance(self):
        svc = EvolutionService()
        respx.delete(f"{BASE}/instance/delete/ventas").mock(
            return_value=httpx.Response(200, json={"status": "deleted"})
        )

        result = await svc.delete_instance("ventas")

        assert result["status"] == "deleted"

    @respx.mock
    async def test_is_reachable_true(self):
        svc = EvolutionService()
        respx.get(f"{BASE}/").mock(return_value=httpx.Response(200))

        assert await svc.is_reachable() is True

    @respx.mock
    async def test_is_reachable_false_on_error(self):
        svc = EvolutionService()
        respx.get(f"{BASE}/").mock(side_effect=httpx.ConnectError("refused"))

        assert await svc.is_reachable() is False


class TestEvolutionErrors:
    @respx.mock
    async def test_http_error_raises_evolution_api_error(self):
        svc = EvolutionService()
        respx.get(f"{BASE}/instance/connectionState/missing").mock(
            return_value=httpx.Response(404, text="Not found")
        )

        with pytest.raises(EvolutionAPIError) as exc_info:
            await svc.connection_state("missing")

        assert exc_info.value.status_code == 404

    @respx.mock
    async def test_connection_error_raises_evolution_api_error(self):
        svc = EvolutionService()
        respx.get(f"{BASE}/instance/connectionState/ventas").mock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        with pytest.raises(EvolutionAPIError) as exc_info:
            await svc.connection_state("ventas")

        assert exc_info.value.status_code is None

    @respx.mock
    async def test_apikey_header_sent(self):
        svc = EvolutionService()
        route = respx.get(f"{BASE}/instance/fetchInstances").mock(
            return_value=httpx.Response(200, json=[])
        )

        await svc.fetch_instances()

        assert route.calls[0].request.headers["apikey"] == settings.EVOLUTION_API_KEY
