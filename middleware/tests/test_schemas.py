"""Tests for Pydantic schema validation — especially webhook payloads."""

import pytest
from pydantic import ValidationError

from app.schemas.webhook import (
    ConnectionUpdateData,
    EvolutionWebhookPayload,
    MessageUpsertData,
    QRCodeData,
)


class TestEvolutionWebhookPayload:
    def test_valid_minimal(self):
        p = EvolutionWebhookPayload(
            event="messages.upsert",
            instance="ventas",
            data={"key": {"remoteJid": "502xxx@s.whatsapp.net", "fromMe": False, "id": "abc"}},
        )
        assert p.event == "messages.upsert"
        assert p.instance == "ventas"
        assert isinstance(p.data, dict)

    def test_all_optional_fields(self):
        p = EvolutionWebhookPayload(
            event="messages.upsert",
            instance="ventas",
            data={"key": {}},
            date_time="2026-02-26T10:00:00Z",
            server_url="http://evolution-api:8080",
            apikey="some-api-key",
        )
        assert p.server_url == "http://evolution-api:8080"
        assert p.apikey == "some-api-key"
        assert p.date_time is not None

    def test_optional_fields_default_none(self):
        p = EvolutionWebhookPayload(
            event="connection.update",
            instance="ventas",
            data={"state": "open"},
        )
        assert p.date_time is None
        assert p.server_url is None
        assert p.apikey is None

    def test_rejects_list_data(self):
        with pytest.raises(ValidationError) as exc_info:
            EvolutionWebhookPayload(
                event="messages.upsert",
                instance="ventas",
                data=[{"key": "value"}],
            )
        assert "data" in str(exc_info.value)

    def test_rejects_string_data(self):
        with pytest.raises(ValidationError):
            EvolutionWebhookPayload(
                event="messages.upsert",
                instance="ventas",
                data="not a dict",
            )

    def test_missing_event_fails(self):
        with pytest.raises(ValidationError):
            EvolutionWebhookPayload(instance="ventas", data={})

    def test_missing_instance_fails(self):
        with pytest.raises(ValidationError):
            EvolutionWebhookPayload(event="messages.upsert", data={})

    def test_missing_data_fails(self):
        with pytest.raises(ValidationError):
            EvolutionWebhookPayload(event="messages.upsert", instance="ventas")

    def test_empty_data_dict_is_valid(self):
        p = EvolutionWebhookPayload(event="connection.update", instance="ventas", data={})
        assert p.data == {}


class TestMessageUpsertData:
    def test_full_message(self):
        d = MessageUpsertData(
            key={"remoteJid": "502xxx@s.whatsapp.net", "fromMe": False, "id": "3EB0ABC123"},
            pushName="John Doe",
            message={"conversation": "Hello!"},
            messageType="conversation",
            messageTimestamp=1717689097,
        )
        assert d.key.remoteJid == "502xxx@s.whatsapp.net"
        assert d.key.fromMe is False
        assert d.pushName == "John Doe"
        assert d.messageTimestamp == 1717689097

    def test_minimal_message(self):
        d = MessageUpsertData(
            key={"remoteJid": "502xxx@s.whatsapp.net", "fromMe": True, "id": "BAE594"},
        )
        assert d.key.fromMe is True
        assert d.pushName is None
        assert d.message is None


class TestConnectionUpdateData:
    def test_open_state(self):
        d = ConnectionUpdateData(state="open", statusReason=200)
        assert d.state == "open"
        assert d.statusReason == 200

    def test_close_state_no_reason(self):
        d = ConnectionUpdateData(state="close")
        assert d.statusReason is None


class TestQRCodeData:
    def test_qrcode(self):
        d = QRCodeData(qrcode={"base64": "data:image/png;base64,abc", "code": "2@xyz"})
        assert "base64" in d.qrcode
        assert d.qrcode["code"] == "2@xyz"


class TestAdminSchemas:
    def test_admin_instance_response_fields(self):
        from app.schemas.instance import AdminInstanceResponse
        r = AdminInstanceResponse(
            instance_name="ventas",
            evolution_name="acme_ventas",
            tenant_slug="acme",
            state="open",
        )
        assert r.instance_name == "ventas"
        assert r.evolution_name == "acme_ventas"
        assert r.last_event_at is None

    def test_tenant_list_item_has_instance_count(self):
        from app.schemas.tenant import TenantListItem
        from datetime import datetime
        item = TenantListItem(
            slug="acme",
            display_name="Acme Corp",
            odoo_webhook_url="https://x.com",
            is_active=True,
            max_instances=10,
            created_at=datetime.now(),
            instance_count=3,
        )
        assert item.instance_count == 3
