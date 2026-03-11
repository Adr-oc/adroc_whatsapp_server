# Manager TUI — Design Spec
**Date:** 2026-03-11
**Status:** Approved

---

## Overview

Replace `scripts/manage.py` (current argparse CLI) with a full Textual TUI — a sidebar-based admin dashboard for operating the Adroc WhatsApp platform as a SaaS service. The operator manages N tenants (Odoo instances), each with N WhatsApp instances (phone numbers).

---

## Goals

- Replace `scripts/manage.py` entirely — single file, no new directories
- Professional-grade admin tool matching the quality of the Odoo module
- Works locally and against remote middleware (no Docker dependency)
- Fast to use: keyboard-first, minimal clicks to reach any action

---

## Stack

| Dependency | Version | Role |
|---|---|---|
| `textual` | latest | TUI framework |
| `httpx` | already in requirements | HTTP client |
| `python-dotenv` | latest | Load `.env` |

Install: `pip install textual python-dotenv` (httpx already present)

---

## Configuration

On startup, load `ADMIN_API_KEY` and `MIDDLEWARE_URL` in order:

1. Environment variables already exported in shell
2. `.env` file in the current working directory (auto-detected via python-dotenv)
3. If neither found → full-screen error with exact commands to fix

`MIDDLEWARE_URL` defaults to `http://localhost:8000` if not set.

---

## Required Middleware Changes

The TUI uses only `ADMIN_API_KEY`. All instance operations and cross-tenant views therefore require new admin-scoped endpoints. The `/api/logs` endpoint requires a new streaming route and an in-memory log buffer.

### New admin instance endpoints

All require `X-API-Key: ADMIN_API_KEY`.

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/admin/instances` | List all instances across all tenants. Query param: `?tenant=<slug>` to filter. Response: array of `AdminInstanceResponse`. |
| `POST` | `/api/admin/instances` | Create instance. Body: `{tenant_slug, instance_name}`. |
| `PUT` | `/api/admin/instances/{name}/restart` | Restart instance (resolves tenant from instance name). |
| `DELETE` | `/api/admin/instances/{name}` | Delete instance. |
| `DELETE` | `/api/admin/instances/{name}/logout` | Logout instance. |
| `POST` | `/api/admin/instances/{name}/send` | Send test message. Body: `{number, text}`. |

**`AdminInstanceResponse` schema:**
```python
class AdminInstanceResponse(BaseModel):
    instance_name: str          # stripped display name (prefix removed), same as tenant-scoped API
    evolution_name: str         # full prefixed name used in URL paths (e.g. "acme_ventas")
    tenant_slug: str
    state: str
    phone_number: str | None
    last_event_at: datetime | None
```

`instance_name` is stripped of `{tenant_slug}_` prefix for display (consistent with tenant-scoped endpoints). `evolution_name` is the full prefixed name used in URL path params for admin mutation endpoints. The TUI uses `evolution_name` when constructing request URLs.

`last_event_at` SQLAlchemy query:
```python
# Subquery: MAX(created_at) per instance from webhook_events
# Join key: WebhookEvent.instance == Instance.instance_name  (both store full prefixed name)
last_event = (
    select(func.max(WebhookEvent.created_at))
    .where(WebhookEvent.instance == Instance.instance_name)
    .correlate(Instance)
    .scalar_subquery()
)
```

`POST /api/admin/instances` body: `{tenant_slug: str, instance_name: str}`. The admin endpoint applies the same `{tenant_slug}_{instance_name}` prefixing used by `_evo_name()` in the tenant-scoped endpoint before calling Evolution API.

### Update `GET /api/admin/tenants` list response

Add a new `TenantListItem` schema (subtype, used only by `GET /api/admin/tenants`) that extends `TenantResponse` with:
```python
class TenantListItem(TenantResponse):
    instance_count: int
```

`GET /api/admin/tenants` changes its `response_model` to `list[TenantListItem]`. All other tenant endpoints (`GET /{slug}`, `POST`, `PATCH`, `DELETE`) continue using `TenantResponse` unchanged.

The instance count is resolved via a correlated subquery:
```python
count_sub = (
    select(func.count()).select_from(Instance)
    .where(Instance.tenant_id == Tenant.id)
    .scalar_subquery()
)
```

### Update `/api/health` response

- Add `instances.total: int` — total instance count across all tenants.
- Add `workers.queue_size` is already present — confirm field path is `result["workers"]["queue_size"]`.
- Add degraded state: `status` can be `"ok"`, `"degraded"`, or `"error"`.

### New `/api/logs` endpoint

`GET /api/logs` — requires `X-API-Key: ADMIN_API_KEY`

**Query params:**
- `lines=100` — how many recent lines to include in initial response (default 100)
- `follow=true/false` — whether to stream new lines (default `false`)

**Implementation in middleware:**

**Step 1 — In-memory log buffer (`app/main.py`):**

```python
import json
from collections import deque

# Monotonic sequence + ring buffer
_log_seq: int = 0
_log_buffer: list[tuple[int, str]] = []   # (seq, json_str), append-only, capped at 1000
_LOG_BUFFER_MAX = 1000
```

Use a plain `list` with an append-only pattern. Cap it at 1000 entries by slicing: `if len(_log_buffer) > _LOG_BUFFER_MAX: _log_buffer = _log_buffer[-_LOG_BUFFER_MAX:]`. Each entry is a `(seq, json_str)` tuple. The SSE loop filters by `seq > last_sent_seq` — stable because seq numbers are monotonically increasing and never reused.

**Step 2 — `BufferProcessor`:**

```python
def buffer_log_processor(logger, method, event_dict):
    global _log_seq
    _log_seq += 1
    _log_buffer.append((_log_seq, json.dumps(event_dict, default=str)))
    if len(_log_buffer) > _LOG_BUFFER_MAX:
        del _log_buffer[:-_LOG_BUFFER_MAX]
    return event_dict   # pass through unchanged
```

Insert in structlog `processors` chain: after `format_exc_info`, before the final renderer (JSONRenderer or ConsoleRenderer). At this point `event_dict` is a plain Python dict with all processors applied — safe to `json.dumps`.

**Step 3 — Route (`app/routes/logs.py`):**

- `response_model` for `follow=false`: `LogsResponse` schema: `class LogsResponse(BaseModel): lines: list[str]`
- `follow=true`: `StreamingResponse(media_type="text/event-stream")` using an `async def` generator:

```python
async def event_stream(lines: int):
    last_seq = 0
    # Flush recent history first
    recent = [entry for entry in _log_buffer if True][-lines:]
    for seq, line in recent:
        last_seq = max(last_seq, seq)
        yield f"data: {line}\n\n"
    # Then tail new entries
    while True:
        new = [(s, l) for s, l in _log_buffer if s > last_seq]
        for seq, line in new:
            last_seq = seq
            yield f"data: {line}\n\n"
        await asyncio.sleep(0.5)
```

Route location: `app/routes/logs.py`, registered in `main.py` with prefix `/api`.

---

## Screens

### Screen 1 — Dashboard (default on open)

**Layout:** Status cards row (top) + tenants summary table (bottom)

**Status cards (6, semaphore colors):**

| Card | Green | Yellow | Red |
|---|---|---|---|
| Middleware | `status: ok` | `status: degraded` | unreachable (network error) |
| Evolution API | `evolution_api.status: reachable` | — | `unreachable` |
| Database | `database.status: connected` | — | not `connected` |
| Active Tenants | any > 0 | — | 0 |
| Total Instances | sourced from `instances.total` (new field) | — | — |
| Odoo Queue | `workers.queue_size == 0` | 1–50 | > 50 |

**Tenant summary table:** slug, display name, instance_count (new field), max_instances, status

**Refresh:** Auto every 30 seconds. `R` forces immediate refresh. Last-refreshed timestamp shown bottom-right.

---

### Screen 2 — Tenants

**Layout:** Left table (70%) + right detail panel (30%)

**Table columns:** slug, display name, instances (instance_count/max_instances), status dot

**Navigation:** Arrow keys move rows; detail panel updates on selection change.

**Detail panel** (selected tenant):
- slug, display name, Odoo webhook URL, max_instances, created_at
- Action buttons: Edit, Rotate API Key, Deactivate, View Instances

**Keyboard shortcuts:**
- `N` — create tenant modal
- `E` — edit tenant modal (pre-filled)
- `K` — rotate API key → confirm modal → show new key (copyable, shown once)
- `D` — deactivate tenant → confirm modal
- `Enter` — navigate to Instances screen filtered to this tenant
- `/` — inline search filter

**Create/Edit modal fields:** slug (create only), display name, Odoo webhook URL, Odoo API key, max_instances

---

### Screen 3 — Instances

**Layout:** Filter bar + full-width table

**Data source:** `GET /api/admin/instances` (new admin endpoint). Query with `?tenant=<slug>` when filtered.

**Filter bar:** Tenant dropdown (All / specific tenant slug). Updates table live on change.

**Table columns:**
- Instance name
- State (semaphore: green=`open`, yellow=`connecting`, red=`closed`/`error`)
- Phone number (`—` if not connected)
- Tenant slug
- Last webhook (relative time from `last_event_at`, e.g. "2m ago" or `—`)

**Keyboard shortcuts:**
- `N` — create instance modal (select tenant dropdown + instance name field)
- `R` — restart selected instance → confirm → `PUT /api/admin/instances/{name}/restart`
- `L` — logout selected instance → confirm → `DELETE /api/admin/instances/{name}/logout`
- `Del` — delete selected instance → confirm → `DELETE /api/admin/instances/{name}`
- `/` — inline search filter on table
- `X` — export prompt (CSV or JSON) → saves to `./instances-export-YYYYMMDD-HHMMSS.{csv,json}`

---

### Screen 4 — Logs

**Layout:** Full-width scrollable log panel

**Source:** `GET /api/logs?follow=true&lines=100` (SSE stream, admin key)

**Textual implementation:** Use a `Worker` thread running `httpx.stream()` that posts new log lines to the main thread via `app.call_from_thread()`.

**Features:**
- New lines appended at bottom, auto-scrolls unless user has scrolled up manually
- `F` — toggle between raw JSON and pretty-printed format
- `Space` — pause/resume live tail (pausing does not close the stream)
- `C` — clear displayed lines (does not affect server buffer)
- Log level color coding: `info`=default, `warning`=yellow, `error`=red

---

### Screen 5 — Test Message

**Layout:** Centered form

**Flow:**
1. Tenant dropdown → populated from `GET /api/admin/tenants`
2. Instance dropdown → populated from `GET /api/admin/instances?tenant=<slug>`, shows `(state)` next to name
3. Phone number text input (validated: digits + optional `+` prefix)
4. Message text area
5. `Ctrl+Enter` or Send button → `POST /api/admin/instances/{name}/send`

**Result:** Green banner with message ID on success. Red banner with error detail on failure.

---

## Navigation & Global UX

**Sidebar (fixed left, ~160px):**
```
⚡ Adroc WA
─────────────
📊 Dashboard       [1]
🏢 Tenants         [2]
📱 Instancias      [3]
📋 Logs            [4]
💬 Test Mensaje    [5]
─────────────
● <host>:<port>
q Salir  ? Ayuda
```

**Global shortcuts:**
| Key | Action |
|---|---|
| `1`–`5` | Switch screen |
| `R` | Refresh current screen data |
| `Q` | Quit |
| `?` | Toggle help overlay (all shortcuts) |

**Error handling:**
- API errors → inline red banner: HTTP status + message from response body
- Network timeout → yellow banner "Connection timeout", auto-retry once
- 403 → red banner "Invalid admin key — check ADMIN_API_KEY"
- On any screen load failure → show error inline, keep TUI running

**Destructive confirmations:** Modal with action description + `Confirm` / `Esc` to cancel.

---

## File Structure

```
scripts/
└── manage.py    ← single file, replaces current entirely

middleware/app/routes/
└── logs.py      ← new route file

middleware/app/
└── main.py      ← add log_buffer list + BufferProcessor + _log_seq
```

`middleware/app/routes/instances.py` and `tenants.py` get new admin endpoints added.

---

## Out of Scope

- Sending real production messages (Test Message is debug-only)
- Multi-user auth / role separation
- TUI theming / color customization
- Automated alerting / push notifications
