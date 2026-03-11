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
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, ScrollableContainer, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import (
    Button, ContentSwitcher, DataTable, Footer, Input,
    Label, Log, Select, Static, TextArea,
)

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


ADROC_CSS = """
Screen {
    layout: horizontal;
}
#sidebar {
    width: 20;
    background: $panel;
    border-right: tall $primary;
    padding: 1 1;
}
.nav-item {
    width: 1fr;
    height: 2;
    background: transparent;
    border: none;
    color: $text-muted;
    text-align: left;
    padding: 0 1;
}
.nav-item:hover {
    background: $boost;
    color: $text;
}
.nav-item.active {
    background: $primary 20%;
    border-left: outer $primary;
    color: $text;
}
#sidebar-status {
    color: $success;
    text-style: bold;
    padding: 0 1;
}
#content {
    width: 1fr;
    height: 1fr;
}
ContentSwitcher {
    width: 1fr;
    height: 1fr;
}
/* Status cards */
.status-card {
    width: 1fr;
    height: 7;
    border: round $primary;
    padding: 1;
    margin: 0 1;
}
.card-ok { border: round $success; }
.card-warn { border: round $warning; }
.card-err { border: round $error; }
.card-value { text-style: bold; font-size: 4; }
.card-label { color: $text-muted; }
/* Tables */
DataTable { height: 1fr; }
/* Modals */
ConfirmModal > Container {
    width: 60;
    height: auto;
    background: $surface;
    border: round $primary;
    padding: 2 4;
}
FormModal > Container {
    width: 70;
    height: auto;
    background: $surface;
    border: round $primary;
    padding: 2 4;
}
.form-row { height: 3; margin-bottom: 1; }
.form-label { width: 20; color: $text-muted; }
.error-banner {
    background: $error 30%;
    color: $error;
    padding: 0 2;
    height: 1;
}
.success-banner {
    background: $success 30%;
    color: $success;
    padding: 0 2;
    height: 1;
}
"""


# ---------------------------------------------------------------------------
# TUI Widgets
# ---------------------------------------------------------------------------

class Sidebar(Vertical):
    """Fixed left navigation sidebar."""

    active: reactive[str] = reactive("dashboard")

    SCREENS = [
        ("dashboard",  "📊", "Dashboard",  "1"),
        ("tenants",    "🏢", "Tenants",    "2"),
        ("instances",  "📱", "Instancias", "3"),
        ("logs",       "📋", "Logs",       "4"),
        ("send",       "💬", "Test Msg",   "5"),
    ]

    def compose(self) -> ComposeResult:
        yield Label("⚡ Adroc WA", id="sidebar-title")
        yield Label("─" * 16)
        for screen_id, icon, label, key in self.SCREENS:
            yield Button(
                f"{icon} {label}  [{key}]",
                id=f"nav-{screen_id}",
                classes="nav-item" + (" active" if screen_id == "dashboard" else ""),
            )
        yield Label("─" * 16)
        yield Label("● connecting...", id="sidebar-status")

    def watch_active(self, new_id: str) -> None:
        for screen_id, _, _, _ in self.SCREENS:
            btn = self.query_one(f"#nav-{screen_id}", Button)
            if screen_id == new_id:
                btn.add_class("active")
            else:
                btn.remove_class("active")

    def set_status(self, text: str, ok: bool = True) -> None:
        label = self.query_one("#sidebar-status", Label)
        color = "green" if ok else "red"
        label.update(f"[{color}]●[/{color}] {text}")


class ConfirmModal(ModalScreen[bool]):
    """Generic destructive action confirmation."""

    def __init__(self, message: str, confirm_label: str = "Confirm") -> None:
        super().__init__()
        self._message = message
        self._confirm_label = confirm_label

    def compose(self) -> ComposeResult:
        with Container():
            yield Label(self._message, id="confirm-msg")
            yield Label("")
            with Horizontal():
                yield Button(self._confirm_label, variant="error", id="btn-confirm")
                yield Button("Cancel", id="btn-cancel")

    @on(Button.Pressed, "#btn-confirm")
    def do_confirm(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#btn-cancel")
    def do_cancel(self) -> None:
        self.dismiss(False)

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(False)


# ---------------------------------------------------------------------------
# Placeholder views (replaced in subsequent tasks)
# ---------------------------------------------------------------------------

class DashboardView(Vertical):
    """Placeholder — replaced in Task 9."""
    def compose(self) -> ComposeResult:
        yield Label("Dashboard loading...")

class TenantsView(Vertical):
    def compose(self) -> ComposeResult:
        yield Label("Tenants loading...")

class InstancesView(Vertical):
    def compose(self) -> ComposeResult:
        yield Label("Instances loading...")

class LogsView(Vertical):
    def compose(self) -> ComposeResult:
        yield Label("Logs loading...")

class SendMessageView(Vertical):
    def compose(self) -> ComposeResult:
        yield Label("Send Message loading...")


# ---------------------------------------------------------------------------
# Main App
# ---------------------------------------------------------------------------

class AdroCApp(App[None]):
    CSS = ADROC_CSS
    TITLE = "Adroc WhatsApp Manager"
    BINDINGS = [
        Binding("1", "show('dashboard')", "Dashboard", show=False),
        Binding("2", "show('tenants')", "Tenants", show=False),
        Binding("3", "show('instances')", "Instances", show=False),
        Binding("4", "show('logs')", "Logs", show=False),
        Binding("5", "show('send')", "Send Msg", show=False),
        Binding("r", "refresh", "Refresh", show=False),
        Binding("q", "quit", "Quit", show=False),
    ]

    def __init__(self, api: ApiClient) -> None:
        super().__init__()
        self.api = api

    def compose(self) -> ComposeResult:
        yield Sidebar(id="sidebar")
        with Container(id="content"):
            yield ContentSwitcher(
                DashboardView(id="dashboard"),
                TenantsView(id="tenants"),
                InstancesView(id="instances"),
                LogsView(id="logs"),
                SendMessageView(id="send"),
                initial="dashboard",
            )

    def action_show(self, screen_id: str) -> None:
        self.query_one(ContentSwitcher).current = screen_id
        self.query_one(Sidebar).active = screen_id

    def action_refresh(self) -> None:
        current = self.query_one(ContentSwitcher).current
        # Each view handles its own refresh via on_show or explicit method
        view = self.query_one(f"#{current}")
        if hasattr(view, "refresh_data"):
            view.refresh_data()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if not ADMIN_API_KEY:
        print("ERROR: ADMIN_API_KEY not set.")
        print("  Set it in your shell:  export ADMIN_API_KEY=<key>")
        print("  Or add it to .env:     echo 'ADMIN_API_KEY=<key>' >> .env")
        raise SystemExit(1)

    api = ApiClient(MIDDLEWARE_URL, ADMIN_API_KEY)
    AdroCApp(api).run()
