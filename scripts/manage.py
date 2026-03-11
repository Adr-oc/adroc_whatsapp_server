#!/usr/bin/env python3
"""Adroc WhatsApp Server — Interactive TUI Manager.

Usage:
    python scripts/manage.py
    MIDDLEWARE_URL=http://server:8000 ADMIN_API_KEY=xxx python scripts/manage.py

Config loaded from (in order): env vars → .env in current directory.
"""
from __future__ import annotations

import asyncio
import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

# Load .env from current working directory before reading env vars
load_dotenv(Path.cwd() / ".env")

MIDDLEWARE_URL = os.environ.get("MIDDLEWARE_URL", "http://localhost:8000").rstrip("/")
ADMIN_API_KEY = os.environ.get("ADMIN_API_KEY", "")


# ---------------------------------------------------------------------------
# API Client
# ---------------------------------------------------------------------------

class ApiError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        self.status = status
        self.detail = detail
        super().__init__(f"HTTP {status}: {detail}")


class ApiClient:
    def __init__(self, base_url: str, admin_key: str) -> None:
        self.base_url = base_url
        self._headers = {"X-API-Key": admin_key, "Content-Type": "application/json"}

    def _raise(self, resp: httpx.Response) -> None:
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("detail", resp.text)
            except Exception:
                detail = resp.text
            raise ApiError(resp.status_code, str(detail))

    async def health(self) -> dict:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(f"{self.base_url}/api/health")
            self._raise(r)
            return r.json()

    async def list_tenants(self) -> list[dict]:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(f"{self.base_url}/api/admin/tenants", headers=self._headers)
            self._raise(r)
            return r.json()

    async def create_tenant(self, slug: str, display_name: str,
                            odoo_url: str, odoo_key: str, max_instances: int) -> dict:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.post(f"{self.base_url}/api/admin/tenants", headers=self._headers,
                             json={"slug": slug, "display_name": display_name,
                                   "odoo_webhook_url": odoo_url, "odoo_api_key": odoo_key,
                                   "max_instances": max_instances})
            self._raise(r)
            return r.json()

    async def get_tenant(self, slug: str) -> dict:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(f"{self.base_url}/api/admin/tenants/{slug}", headers=self._headers)
            self._raise(r)
            return r.json()

    async def update_tenant(self, slug: str, **kwargs: Any) -> dict:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.patch(f"{self.base_url}/api/admin/tenants/{slug}",
                              headers=self._headers, json=kwargs)
            self._raise(r)
            return r.json()

    async def deactivate_tenant(self, slug: str) -> dict:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.delete(f"{self.base_url}/api/admin/tenants/{slug}", headers=self._headers)
            self._raise(r)
            return r.json()

    async def rotate_key(self, slug: str) -> dict:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.post(f"{self.base_url}/api/admin/tenants/{slug}/rotate-key",
                             headers=self._headers)
            self._raise(r)
            return r.json()

    async def list_instances(self, tenant: str | None = None) -> list[dict]:
        params = {"tenant": tenant} if tenant else {}
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(f"{self.base_url}/api/admin/instances",
                            headers=self._headers, params=params)
            self._raise(r)
            return r.json()

    async def create_instance(self, tenant_slug: str, instance_name: str) -> dict:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.post(f"{self.base_url}/api/admin/instances", headers=self._headers,
                             json={"tenant_slug": tenant_slug, "instance_name": instance_name})
            self._raise(r)
            return r.json()

    async def restart_instance(self, evo_name: str) -> dict:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.put(f"{self.base_url}/api/admin/instances/{evo_name}/restart",
                            headers=self._headers)
            self._raise(r)
            return r.json()

    async def delete_instance(self, evo_name: str) -> dict:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.delete(f"{self.base_url}/api/admin/instances/{evo_name}",
                               headers=self._headers)
            self._raise(r)
            return r.json()

    async def logout_instance(self, evo_name: str) -> dict:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.delete(f"{self.base_url}/api/admin/instances/{evo_name}/logout",
                               headers=self._headers)
            self._raise(r)
            return r.json()

    async def send_message(self, evo_name: str, number: str, text: str) -> dict:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.post(f"{self.base_url}/api/admin/instances/{evo_name}/send",
                             headers=self._headers, json={"number": number, "text": text})
            self._raise(r)
            return r.json()


# ---------------------------------------------------------------------------
# Entry point (TUI classes added in subsequent tasks)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if not ADMIN_API_KEY:
        print("ERROR: ADMIN_API_KEY not set.")
        print("  Set it in your shell:  export ADMIN_API_KEY=<key>")
        print("  Or add it to .env:     echo 'ADMIN_API_KEY=<key>' >> .env")
        raise SystemExit(1)
    print("API client ready — TUI coming in next task")
