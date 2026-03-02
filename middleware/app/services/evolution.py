from typing import Any

import httpx
import structlog

from app.config import settings
from app.exceptions import EvolutionAPIError

log = structlog.get_logger()


class EvolutionService:
    """Client for Evolution API. All methods return raw JSON dicts."""

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=settings.EVOLUTION_API_URL,
                headers={"apikey": settings.EVOLUTION_API_KEY},
                timeout=30.0,
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = await self.client.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            raise EvolutionAPIError(
                f"{method} {path} failed: {e.response.text}",
                status_code=e.response.status_code,
            ) from e
        except httpx.RequestError as e:
            raise EvolutionAPIError(f"{method} {path} connection error: {e}") from e

    async def create_instance(self, instance_name: str) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/instance/create",
            json={
                "instanceName": instance_name,
                "integration": "WHATSAPP-BAILEYS",
                "qrcode": True,
                "webhook": {
                    "url": "http://middleware:8000/webhooks/evolution",
                    "byEvents": False,
                    "base64": True,
                    "events": [
                        "QRCODE_UPDATED",
                        "MESSAGES_UPSERT",
                        "MESSAGES_UPDATE",
                        "MESSAGES_DELETE",
                        "SEND_MESSAGE",
                        "CONNECTION_UPDATE",
                    ],
                },
            },
        )

    async def fetch_instances(self) -> list[dict[str, Any]]:
        return await self._request("GET", "/instance/fetchInstances")

    async def connection_state(self, instance_name: str) -> dict[str, Any]:
        return await self._request("GET", f"/instance/connectionState/{instance_name}")

    async def connect(self, instance_name: str) -> dict[str, Any]:
        return await self._request("GET", f"/instance/connect/{instance_name}")

    async def send_text(
        self, instance_name: str, number: str, text: str
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/message/sendText/{instance_name}",
            json={
                "number": number,
                "text": text,
                "delay": 1200,
                "presence": "composing",
            },
        )

    async def send_media(
        self,
        instance_name: str,
        number: str,
        media_url: str,
        media_type: str = "image",
        caption: str | None = None,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/message/sendMedia/{instance_name}",
            json={
                "number": number,
                "mediatype": media_type,
                "media": media_url,
                "caption": caption or "",
            },
        )

    async def delete_instance(self, instance_name: str) -> dict[str, Any]:
        return await self._request("DELETE", f"/instance/delete/{instance_name}")

    async def restart_instance(self, instance_name: str) -> dict[str, Any]:
        return await self._request("PUT", f"/instance/restart/{instance_name}")

    async def logout_instance(self, instance_name: str) -> dict[str, Any]:
        return await self._request("DELETE", f"/instance/logout/{instance_name}")

    async def is_reachable(self) -> bool:
        try:
            await self.client.get("/")
            return True
        except Exception:
            return False


evolution_service = EvolutionService()
