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
    Label, Log, Markdown, Select, Static, TextArea,
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
# Task 9: Dashboard screen
# ---------------------------------------------------------------------------

class StatusCard(Vertical):
    """A colored card showing a single metric."""

    def __init__(self, card_id: str, label: str) -> None:
        super().__init__(id=f"card-{card_id}", classes="status-card")
        self._label = label

    def compose(self) -> ComposeResult:
        yield Label("…", classes="card-value", id=f"val-{self.id}")
        yield Label(self._label, classes="card-label")

    def update(self, value: str, state: str = "ok") -> None:
        self.query_one(f"#val-{self.id}", Label).update(value)
        for cls in ("card-ok", "card-warn", "card-err"):
            self.remove_class(cls)
        self.add_class({"ok": "card-ok", "warn": "card-warn", "err": "card-err"}[state])


class DashboardView(Vertical):
    BORDER_TITLE = "Dashboard"

    def compose(self) -> ComposeResult:
        with Horizontal(id="cards-row"):
            yield StatusCard("middleware", "Middleware")
            yield StatusCard("evolution", "Evolution API")
            yield StatusCard("db", "Database")
            yield StatusCard("tenants", "Tenants activos")
            yield StatusCard("instances", "Instancias totales")
            yield StatusCard("queue", "Cola Odoo")
        yield Label("TENANTS", id="tenants-title")
        yield DataTable(id="dash-tenant-table", cursor_type="none")
        yield Label("", id="last-refresh")

    def on_mount(self) -> None:
        table = self.query_one("#dash-tenant-table", DataTable)
        table.add_columns("TENANT", "NOMBRE", "INST", "MAX", "ESTADO")
        self.refresh_data()
        self.set_interval(30, self.refresh_data)

    @work(exclusive=True)
    async def refresh_data(self) -> None:
        try:
            health = await self.app.api.health()
            tenants = await self.app.api.list_tenants()
        except Exception as e:
            self.app.query_one(Sidebar).set_status("error", ok=False)
            self.notify(f"Dashboard error: {e}", severity="error", timeout=5)
            return

        # Update cards
        status = health.get("status", "error")
        self._update_card("middleware", status.upper(),
                          "ok" if status == "ok" else "warn" if status == "degraded" else "err")

        evo = health.get("evolution_api", {}).get("status", "unreachable")
        self._update_card("evolution", evo, "ok" if evo == "reachable" else "err")

        db = health.get("database", {}).get("status", "disconnected")
        self._update_card("db", db, "ok" if db == "connected" else "err")

        active_t = health.get("tenants", {}).get("active", 0)
        self._update_card("tenants", str(active_t), "ok" if active_t > 0 else "err")

        total_i = health.get("instances", {}).get("total", 0)
        self._update_card("instances", str(total_i), "ok")

        queue = health.get("workers", {}).get("queue_size", 0)
        q_state = "ok" if queue == 0 else "warn" if queue <= 50 else "err"
        self._update_card("queue", str(queue), q_state)

        # Update sidebar status
        self.app.query_one(Sidebar).set_status(
            f"{MIDDLEWARE_URL.split('//')[1]}", ok=(status == "ok")
        )

        # Update tenant table
        table = self.query_one("#dash-tenant-table", DataTable)
        table.clear()
        for t in tenants:
            state_icon = "✓" if t.get("is_active") else "✗"
            table.add_row(
                t["slug"],
                t["display_name"],
                str(t.get("instance_count", 0)),
                str(t.get("max_instances", "?")),
                state_icon,
            )

        ts = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        self.query_one("#last-refresh", Label).update(f"Refreshed: {ts}  [dim](R to force)[/dim]")

    def _update_card(self, card_id: str, value: str, state: str) -> None:
        self.query_one(f"#card-{card_id}", StatusCard).update(value, state)


# ---------------------------------------------------------------------------
# Task 10: Tenants screen
# ---------------------------------------------------------------------------

class TenantDetailPanel(Vertical):
    """Right panel showing selected tenant details and actions."""

    def compose(self) -> ComposeResult:
        yield Label("Select a tenant", id="detail-title")
        yield Label("", id="detail-slug")
        yield Label("", id="detail-name")
        yield Label("", id="detail-url")
        yield Label("", id="detail-instances")
        yield Label("", id="detail-created")
        yield Label("")
        yield Button("📱 Ver instancias", id="btn-view-instances", disabled=True)
        yield Button("✏️  Editar",         id="btn-edit",          disabled=True)
        yield Button("🔑 Rotar API key",   id="btn-rotate",        disabled=True)
        yield Button("⛔ Desactivar",      id="btn-deactivate",    variant="error", disabled=True)

    def show_tenant(self, t: dict) -> None:
        self.query_one("#detail-title", Label).update(f"[bold]{t['slug']}[/bold]")
        self.query_one("#detail-slug", Label).update(f"Slug: {t['slug']}")
        self.query_one("#detail-name", Label).update(f"Nombre: {t['display_name']}")
        url = t.get("odoo_webhook_url", "")
        self.query_one("#detail-url", Label).update(f"URL: [link]{url[:40]}[/link]")
        cnt = t.get("instance_count", "?")
        mx = t.get("max_instances", "?")
        self.query_one("#detail-instances", Label).update(f"Instancias: {cnt}/{mx}")
        created = t.get("created_at", "")[:10]
        self.query_one("#detail-created", Label).update(f"Creado: {created}")
        for btn_id in ("btn-view-instances", "btn-edit", "btn-rotate", "btn-deactivate"):
            self.query_one(f"#{btn_id}", Button).disabled = False

    def clear(self) -> None:
        self.query_one("#detail-title", Label).update("Select a tenant")
        for btn_id in ("btn-view-instances", "btn-edit", "btn-rotate", "btn-deactivate"):
            self.query_one(f"#{btn_id}", Button).disabled = True


class CreateTenantModal(ModalScreen[dict | None]):
    def compose(self) -> ComposeResult:
        with Container():
            yield Label("Nuevo Tenant", id="modal-title")
            yield Label("")
            with Horizontal(classes="form-row"):
                yield Label("Slug:", classes="form-label")
                yield Input(placeholder="acme", id="f-slug")
            with Horizontal(classes="form-row"):
                yield Label("Nombre:", classes="form-label")
                yield Input(placeholder="Acme Corp", id="f-name")
            with Horizontal(classes="form-row"):
                yield Label("Odoo URL:", classes="form-label")
                yield Input(placeholder="https://acme.odoo.com/whatsapp/webhook", id="f-url")
            with Horizontal(classes="form-row"):
                yield Label("Odoo API key:", classes="form-label")
                yield Input(placeholder="secret", id="f-key", password=True)
            with Horizontal(classes="form-row"):
                yield Label("Max instancias:", classes="form-label")
                yield Input(value="10", id="f-max")
            yield Label("")
            with Horizontal():
                yield Button("Crear", variant="primary", id="btn-ok")
                yield Button("Cancelar", id="btn-cancel")

    @on(Button.Pressed, "#btn-ok")
    def submit(self) -> None:
        slug = self.query_one("#f-slug", Input).value.strip()
        name = self.query_one("#f-name", Input).value.strip()
        url  = self.query_one("#f-url", Input).value.strip()
        key  = self.query_one("#f-key", Input).value.strip()
        try:
            max_inst = int(self.query_one("#f-max", Input).value.strip() or "10")
        except ValueError:
            max_inst = 10
        if not all([slug, name, url, key]):
            self.notify("Todos los campos son requeridos.", severity="error")
            return
        self.dismiss({"slug": slug, "display_name": name, "odoo_url": url,
                      "odoo_key": key, "max_instances": max_inst})

    @on(Button.Pressed, "#btn-cancel")
    def cancel(self) -> None:
        self.dismiss(None)

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(None)


class EditTenantModal(ModalScreen[dict | None]):
    def __init__(self, tenant: dict) -> None:
        super().__init__()
        self._tenant = tenant

    def compose(self) -> ComposeResult:
        t = self._tenant
        with Container():
            yield Label(f"Editar: {t['slug']}", id="modal-title")
            yield Label("")
            with Horizontal(classes="form-row"):
                yield Label("Nombre:", classes="form-label")
                yield Input(value=t.get("display_name", ""), id="f-name")
            with Horizontal(classes="form-row"):
                yield Label("Odoo URL:", classes="form-label")
                yield Input(value=t.get("odoo_webhook_url", ""), id="f-url")
            with Horizontal(classes="form-row"):
                yield Label("Odoo API key:", classes="form-label")
                yield Input(placeholder="(leave blank to keep)", id="f-key", password=True)
            with Horizontal(classes="form-row"):
                yield Label("Max instancias:", classes="form-label")
                yield Input(value=str(t.get("max_instances", 10)), id="f-max")
            yield Label("")
            with Horizontal():
                yield Button("Guardar", variant="primary", id="btn-ok")
                yield Button("Cancelar", id="btn-cancel")

    @on(Button.Pressed, "#btn-ok")
    def submit(self) -> None:
        updates: dict = {}
        name = self.query_one("#f-name", Input).value.strip()
        if name:
            updates["display_name"] = name
        url = self.query_one("#f-url", Input).value.strip()
        if url:
            updates["odoo_webhook_url"] = url
        key = self.query_one("#f-key", Input).value.strip()
        if key:
            updates["odoo_api_key"] = key
        max_val = self.query_one("#f-max", Input).value.strip()
        try:
            updates["max_instances"] = int(max_val)
        except ValueError:
            pass
        self.dismiss(updates if updates else None)

    @on(Button.Pressed, "#btn-cancel")
    def cancel(self) -> None:
        self.dismiss(None)

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(None)


class TenantsView(Horizontal):
    BORDER_TITLE = "Tenants"

    _tenants: list[dict] = []
    _selected_tenant: dict | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="tenant-left"):
            with Horizontal(id="tenant-toolbar"):
                yield Label("Tenants", id="tenant-count")
                yield Button("+ Nuevo", id="btn-new-tenant", variant="primary")
            yield DataTable(id="tenant-table", cursor_type="row")
            yield Label("/ para buscar  N nuevo  E editar  K rotar key  D desactivar",
                        id="tenant-hint")
        yield TenantDetailPanel(id="tenant-detail")

    def on_mount(self) -> None:
        table = self.query_one("#tenant-table", DataTable)
        table.add_columns("SLUG", "NOMBRE", "INST", "ESTADO")
        self.refresh_data()

    @work(exclusive=True)
    async def refresh_data(self) -> None:
        try:
            tenants = await self.app.api.list_tenants()
        except ApiError as e:
            self.notify(f"Error: {e.detail}", severity="error")
            return
        self._tenants = tenants
        table = self.query_one("#tenant-table", DataTable)
        table.clear()
        for t in tenants:
            state = "✓ activo" if t.get("is_active") else "✗ inactivo"
            cnt = t.get("instance_count", 0)
            mx = t.get("max_instances", "?")
            table.add_row(t["slug"], t["display_name"], f"{cnt}/{mx}", state,
                          key=t["slug"])
        self.query_one("#tenant-count", Label).update(f"{len(tenants)} tenants")

    @on(DataTable.RowSelected, "#tenant-table")
    def on_row_selected(self, event: DataTable.RowSelected) -> None:
        slug = str(event.row_key.value)
        self._selected_tenant = next((t for t in self._tenants if t["slug"] == slug), None)
        if self._selected_tenant:
            self.query_one(TenantDetailPanel).show_tenant(self._selected_tenant)

    @on(Button.Pressed, "#btn-new-tenant")
    async def new_tenant(self) -> None:
        result = await self.app.push_screen_wait(CreateTenantModal())
        if result:
            try:
                data = await self.app.api.create_tenant(**result)
                api_key = data.get("api_key", "")
                self.notify(f"Tenant creado. API KEY: {api_key}", severity="information",
                            timeout=30)
                self.refresh_data()
            except ApiError as e:
                self.notify(f"Error: {e.detail}", severity="error")

    @on(Button.Pressed, "#btn-view-instances")
    def view_instances(self) -> None:
        if self._selected_tenant:
            self.app.action_show("instances")
            inst_view = self.app.query_one(InstancesView)
            inst_view.filter_slug = self._selected_tenant["slug"]

    @on(Button.Pressed, "#btn-edit")
    async def edit_tenant(self) -> None:
        if not self._selected_tenant:
            return
        result = await self.app.push_screen_wait(EditTenantModal(self._selected_tenant))
        if result:
            try:
                await self.app.api.update_tenant(self._selected_tenant["slug"], **result)
                self.notify("Tenant actualizado.", severity="information")
                self.refresh_data()
            except ApiError as e:
                self.notify(f"Error: {e.detail}", severity="error")

    @on(Button.Pressed, "#btn-rotate")
    async def rotate_key(self) -> None:
        if not self._selected_tenant:
            return
        slug = self._selected_tenant["slug"]
        confirmed = await self.app.push_screen_wait(
            ConfirmModal(f"Rotar API key de '{slug}'?\nLa clave actual quedará inválida.")
        )
        if confirmed:
            try:
                data = await self.app.api.rotate_key(slug)
                new_key = data.get("api_key", "")
                self.notify(f"Nueva API KEY: {new_key}", severity="information", timeout=60)
            except ApiError as e:
                self.notify(f"Error: {e.detail}", severity="error")

    @on(Button.Pressed, "#btn-deactivate")
    async def deactivate_tenant(self) -> None:
        if not self._selected_tenant:
            return
        slug = self._selected_tenant["slug"]
        confirmed = await self.app.push_screen_wait(
            ConfirmModal(f"Desactivar tenant '{slug}'?", confirm_label="Desactivar")
        )
        if confirmed:
            try:
                await self.app.api.deactivate_tenant(slug)
                self.notify(f"Tenant '{slug}' desactivado.", severity="warning")
                self.query_one(TenantDetailPanel).clear()
                self.refresh_data()
            except ApiError as e:
                self.notify(f"Error: {e.detail}", severity="error")


# ---------------------------------------------------------------------------
# Task 11: Instances screen
# ---------------------------------------------------------------------------

def _state_display(state: str) -> str:
    icons = {"open": "[green]● open[/green]", "connecting": "[yellow]◉ connecting[/yellow]"}
    return icons.get(state, f"[red]○ {state}[/red]")


def _rel_time(dt_str: str | None) -> str:
    if not dt_str:
        return "—"
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        diff = datetime.now(timezone.utc) - dt
        secs = int(diff.total_seconds())
        if secs < 60:
            return f"{secs}s ago"
        if secs < 3600:
            return f"{secs // 60}m ago"
        return f"{secs // 3600}h ago"
    except Exception:
        return dt_str[:16]


class CreateInstanceModal(ModalScreen[dict | None]):
    def __init__(self, tenant_options: list[tuple[str, str]]) -> None:
        super().__init__()
        self._options = tenant_options

    def compose(self) -> ComposeResult:
        with Container():
            yield Label("Nueva Instancia", id="modal-title")
            yield Label("")
            with Horizontal(classes="form-row"):
                yield Label("Tenant:", classes="form-label")
                yield Select(self._options, id="f-tenant")
            with Horizontal(classes="form-row"):
                yield Label("Nombre:", classes="form-label")
                yield Input(placeholder="ventas", id="f-name")
            yield Label("")
            with Horizontal():
                yield Button("Crear", variant="primary", id="btn-ok")
                yield Button("Cancelar", id="btn-cancel")

    @on(Button.Pressed, "#btn-ok")
    def submit(self) -> None:
        tenant_slug = self.query_one("#f-tenant", Select).value
        name = self.query_one("#f-name", Input).value.strip()
        if tenant_slug is Select.BLANK or not name:
            self.notify("Tenant y nombre son requeridos.", severity="error")
            return
        self.dismiss({"tenant_slug": str(tenant_slug), "instance_name": name})

    @on(Button.Pressed, "#btn-cancel")
    def cancel(self) -> None:
        self.dismiss(None)

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(None)


class InstancesView(Vertical):
    BORDER_TITLE = "Instancias"

    filter_slug: reactive[str | None] = reactive(None)

    def compose(self) -> ComposeResult:
        with Horizontal(id="inst-toolbar"):
            yield Label("Tenant:", id="inst-filter-label")
            yield Select([("— Todos —", "")], id="inst-filter", value="")
            yield Label("", id="inst-count")
            yield Button("+ Nueva", id="btn-new-inst", variant="primary")
        yield DataTable(id="inst-table", cursor_type="row")
        yield Label(
            "N nueva  R restart  L logout  Del eliminar  X exportar  / buscar",
            id="inst-hint"
        )

    def on_mount(self) -> None:
        self._instances: list[dict] = []
        self._tenants: list[dict] = []
        table = self.query_one("#inst-table", DataTable)
        table.add_columns("INSTANCIA", "ESTADO", "TELÉFONO", "TENANT", "ÚLTIMO WEBHOOK")
        self.refresh_data()

    def watch_filter_slug(self, slug: str | None) -> None:
        try:
            sel = self.query_one("#inst-filter", Select)
            sel.value = slug or ""
        except Exception:
            pass

    @work(exclusive=True)
    async def refresh_data(self) -> None:
        try:
            tenant_filter = self.query_one("#inst-filter", Select).value or None
            self._instances = await self.app.api.list_instances(tenant=tenant_filter or None)
            self._tenants = await self.app.api.list_tenants()
        except ApiError as e:
            self.notify(f"Error: {e.detail}", severity="error")
            return

        # Update filter dropdown
        sel = self.query_one("#inst-filter", Select)
        options: list[tuple[str, str]] = [("— Todos —", "")]
        options += [(t["display_name"], t["slug"]) for t in self._tenants]
        sel.set_options(options)

        # Update table
        table = self.query_one("#inst-table", DataTable)
        table.clear()
        for inst in self._instances:
            table.add_row(
                inst["instance_name"],
                _state_display(inst.get("state", "unknown")),
                inst.get("phone_number") or "—",
                inst.get("tenant_slug", ""),
                _rel_time(inst.get("last_event_at")),
                key=inst["evolution_name"],
            )
        self.query_one("#inst-count", Label).update(f"{len(self._instances)} instancias")

    @on(Select.Changed, "#inst-filter")
    def filter_changed(self, event: Select.Changed) -> None:
        self.refresh_data()

    def _selected_inst(self) -> dict | None:
        table = self.query_one("#inst-table", DataTable)
        if table.cursor_row < 0:
            return None
        cursor_key = table.coordinate_to_cell_key(table.cursor_coordinate)
        evo_name = str(cursor_key.row_key.value)
        return next((i for i in self._instances if i["evolution_name"] == evo_name), None)

    @on(Button.Pressed, "#btn-new-inst")
    async def new_instance(self) -> None:
        if not self._tenants:
            self.notify("No hay tenants disponibles.", severity="error")
            return
        options = [(t["display_name"], t["slug"]) for t in self._tenants]
        result = await self.app.push_screen_wait(CreateInstanceModal(options))
        if result:
            try:
                await self.app.api.create_instance(**result)
                self.notify("Instancia creada.", severity="information")
                self.refresh_data()
            except ApiError as e:
                self.notify(f"Error: {e.detail}", severity="error")

    def on_key(self, event) -> None:
        key = event.key
        if key == "r":
            self.app.call_later(self._restart_selected)
        elif key == "l":
            self.app.call_later(self._logout_selected)
        elif key == "delete":
            self.app.call_later(self._delete_selected)
        elif key == "x":
            self._export()

    async def _restart_selected(self) -> None:
        inst = self._selected_inst()
        if not inst:
            return
        confirmed = await self.app.push_screen_wait(
            ConfirmModal(f"Restart '{inst['instance_name']}'?")
        )
        if confirmed:
            try:
                await self.app.api.restart_instance(inst["evolution_name"])
                self.notify("Instancia reiniciada.", severity="information")
                self.refresh_data()
            except ApiError as e:
                self.notify(f"Error: {e.detail}", severity="error")

    async def _logout_selected(self) -> None:
        inst = self._selected_inst()
        if not inst:
            return
        confirmed = await self.app.push_screen_wait(
            ConfirmModal(f"Logout '{inst['instance_name']}'?", confirm_label="Logout")
        )
        if confirmed:
            try:
                await self.app.api.logout_instance(inst["evolution_name"])
                self.notify("Instancia desconectada.", severity="warning")
                self.refresh_data()
            except ApiError as e:
                self.notify(f"Error: {e.detail}", severity="error")

    async def _delete_selected(self) -> None:
        inst = self._selected_inst()
        if not inst:
            return
        confirmed = await self.app.push_screen_wait(
            ConfirmModal(f"ELIMINAR '{inst['instance_name']}'?", confirm_label="ELIMINAR")
        )
        if confirmed:
            try:
                await self.app.api.delete_instance(inst["evolution_name"])
                self.notify("Instancia eliminada.", severity="warning")
                self.refresh_data()
            except ApiError as e:
                self.notify(f"Error: {e.detail}", severity="error")

    @work(thread=True)
    def _export(self) -> None:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = Path.cwd() / f"instances-export-{ts}.csv"
        try:
            with open(path, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=[
                    "instance_name", "evolution_name", "tenant_slug",
                    "state", "phone_number", "last_event_at"
                ])
                w.writeheader()
                w.writerows(self._instances)
            self.app.call_from_thread(self.notify, f"Exportado: {path.name}", severity="information")
        except OSError as e:
            self.app.call_from_thread(self.notify, f"Export error: {e}", severity="error")


# ---------------------------------------------------------------------------
# Task 12: Logs screen
# ---------------------------------------------------------------------------

class LogsView(Vertical):
    BORDER_TITLE = "Logs"
    BINDINGS = [
        Binding("f", "toggle_format", "Toggle JSON/Pretty", show=False),
        Binding("space", "toggle_pause", "Pause/Resume", show=False),
        Binding("c", "clear_logs", "Clear", show=False),
    ]

    _pretty: bool = False
    _paused: bool = False

    def compose(self) -> ComposeResult:
        with Horizontal(id="logs-toolbar"):
            yield Label("[green]● Live[/green]", id="logs-status")
            yield Label("  F: JSON/Pretty  Space: Pause  C: Clear", id="logs-hint")
        yield Log(id="log-widget", highlight=True, auto_scroll=True)

    def on_show(self) -> None:
        self.start_stream()

    @work(exclusive=True)
    async def start_stream(self) -> None:
        url = f"{MIDDLEWARE_URL}/api/logs?follow=true&lines=100"
        headers = self.app.api._headers
        log_widget = self.query_one("#log-widget", Log)
        status = self.query_one("#logs-status", Label)

        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream("GET", url, headers=headers) as resp:
                    if resp.status_code == 403:
                        log_widget.write_line("[red]Error: Invalid admin key[/red]")
                        return
                    status.update("[green]● Live[/green]")
                    async for line in resp.aiter_lines():
                        if self._paused:
                            continue
                        if line.startswith("data: "):
                            self._write_log(line[6:])
        except httpx.ConnectError:
            log_widget.write_line("[red]Error: Cannot connect to middleware[/red]")
            status.update("[red]● Disconnected[/red]")
        except Exception as e:
            log_widget.write_line(f"[red]Stream error: {e}[/red]")
            status.update("[yellow]● Error[/yellow]")

    def _write_log(self, json_str: str) -> None:
        log_widget = self.query_one("#log-widget", Log)
        if not self._pretty:
            log_widget.write_line(json_str)
            return
        try:
            data = json.loads(json_str)
            level = data.get("level", "info").upper()
            event = data.get("event", "")
            ts = str(data.get("timestamp", ""))[:19]
            color = {"ERROR": "red", "WARNING": "yellow", "INFO": "green"}.get(level, "white")
            extra = {k: v for k, v in data.items()
                     if k not in ("level", "event", "timestamp")}
            extra_str = " ".join(f"{k}={v}" for k, v in extra.items()) if extra else ""
            log_widget.write_line(
                f"[{color}][{ts}] [{level}][/{color}] {event}  [dim]{extra_str}[/dim]"
            )
        except json.JSONDecodeError:
            log_widget.write_line(json_str)

    def action_toggle_format(self) -> None:
        self._pretty = not self._pretty
        mode = "Pretty" if self._pretty else "JSON"
        self.notify(f"Modo: {mode}", timeout=1)

    def action_toggle_pause(self) -> None:
        self._paused = not self._paused
        status = self.query_one("#logs-status", Label)
        if self._paused:
            status.update("[yellow]⏸ Paused[/yellow]")
        else:
            status.update("[green]● Live[/green]")

    def action_clear_logs(self) -> None:
        self.query_one("#log-widget", Log).clear()


# ---------------------------------------------------------------------------
# Task 13: Test Message screen
# ---------------------------------------------------------------------------

class SendMessageView(Vertical):
    BORDER_TITLE = "Test Mensaje"

    def compose(self) -> ComposeResult:
        yield Label("Enviar mensaje de prueba", id="send-title")
        yield Label("")
        with Horizontal(classes="form-row"):
            yield Label("Tenant:", classes="form-label")
            yield Select([("Cargando...", "")], id="send-tenant")
        with Horizontal(classes="form-row"):
            yield Label("Instancia:", classes="form-label")
            yield Select([("Selecciona tenant primero", "")], id="send-instance")
        with Horizontal(classes="form-row"):
            yield Label("Número:", classes="form-label")
            yield Input(placeholder="502XXXXXXXX", id="send-number")
        yield Label("Mensaje:")
        yield TextArea(id="send-text")
        yield Label("")
        with Horizontal():
            yield Button("Enviar  [Ctrl+Enter]", variant="primary", id="btn-send")
        yield Label("", id="send-result")

    def on_mount(self) -> None:
        self._tenants: list[dict] = []
        self._instances: list[dict] = []
        self.load_tenants()

    @work(exclusive=True)
    async def load_tenants(self) -> None:
        try:
            self._tenants = await self.app.api.list_tenants()
            options = [(t["display_name"], t["slug"]) for t in self._tenants]
            sel = self.query_one("#send-tenant", Select)
            sel.set_options(options)
        except ApiError as e:
            self.notify(f"Error cargando tenants: {e.detail}", severity="error")

    @on(Select.Changed, "#send-tenant")
    def tenant_changed(self, event: Select.Changed) -> None:
        if event.value is Select.BLANK:
            return
        self._load_instances_for_tenant(str(event.value))

    @work(exclusive=True)
    async def _load_instances_for_tenant(self, slug: str) -> None:
        try:
            self._instances = await self.app.api.list_instances(tenant=slug)
            options = [
                (f"{i['instance_name']} ({i['state']})", i["evolution_name"])
                for i in self._instances
            ]
            self.query_one("#send-instance", Select).set_options(options)
        except ApiError as e:
            self.notify(f"Error cargando instancias: {e.detail}", severity="error")

    @on(Button.Pressed, "#btn-send")
    async def send_message(self) -> None:
        inst_sel = self.query_one("#send-instance", Select)
        evo_name = "" if inst_sel.value is Select.BLANK else str(inst_sel.value)
        number = self.query_one("#send-number", Input).value.strip()
        text = self.query_one("#send-text", TextArea).text.strip()

        if not all([evo_name, number, text]):
            self.notify("Completa todos los campos.", severity="error")
            return

        result_label = self.query_one("#send-result", Label)
        result_label.update("[yellow]Enviando...[/yellow]")
        try:
            data = await self.app.api.send_message(evo_name, number, text)
            msg_id = data.get("key", {}).get("id", "?")
            result_label.update(f"[green]✓ Enviado! Message ID: {msg_id}[/green]")
        except ApiError as e:
            result_label.update(f"[red]✗ Error: {e.detail}[/red]")

    def on_key(self, event) -> None:
        if event.key == "ctrl+enter":
            self.app.call_later(self.send_message)


# ---------------------------------------------------------------------------
# Task 13 (continued): Help overlay
# ---------------------------------------------------------------------------

class HelpOverlay(ModalScreen):
    HELP_TEXT = """\
# Adroc WA Manager — Atajos de teclado

## Navegación
  1-5     Cambiar pantalla
  Q       Salir
  R       Refrescar pantalla actual
  ?       Mostrar/ocultar esta ayuda

## Tenants (pantalla 2)
  N       Nuevo tenant
  E       Editar tenant seleccionado
  K       Rotar API key
  D       Desactivar tenant
  Enter   Ver instancias del tenant

## Instancias (pantalla 3)
  N       Nueva instancia
  R       Restart instancia seleccionada
  L       Logout instancia seleccionada
  Del     Eliminar instancia seleccionada
  X       Exportar tabla a CSV

## Logs (pantalla 4)
  F       Toggle JSON / Pretty print
  Space   Pausar / Reanudar stream
  C       Limpiar pantalla

## Modales
  Enter   Confirmar
  Esc     Cancelar
"""

    def compose(self) -> ComposeResult:
        with Container(id="help-container"):
            yield Markdown(self.HELP_TEXT)
            yield Button("Cerrar  [Esc]", id="btn-close")

    @on(Button.Pressed, "#btn-close")
    def close(self) -> None:
        self.dismiss()

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss()


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
        Binding("question_mark", "show_help", "Help", show=False),
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

    async def action_show_help(self) -> None:
        await self.push_screen(HelpOverlay())


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
