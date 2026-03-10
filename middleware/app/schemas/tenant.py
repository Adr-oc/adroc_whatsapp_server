from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, field_validator


class CreateTenantRequest(BaseModel):
    slug: str
    display_name: str
    odoo_webhook_url: str
    odoo_api_key: str
    max_instances: int = 10

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v: str) -> str:
        if not re.match(r"^[a-z0-9_-]+$", v):
            raise ValueError("slug must contain only lowercase letters, numbers, hyphens, and underscores")
        return v


class UpdateTenantRequest(BaseModel):
    display_name: str | None = None
    odoo_webhook_url: str | None = None
    odoo_api_key: str | None = None
    max_instances: int | None = None
    is_active: bool | None = None


class TenantResponse(BaseModel):
    slug: str
    display_name: str
    odoo_webhook_url: str
    is_active: bool
    max_instances: int
    created_at: datetime

    model_config = {"from_attributes": True}


class TenantCreatedResponse(BaseModel):
    tenant: TenantResponse
    api_key: str
