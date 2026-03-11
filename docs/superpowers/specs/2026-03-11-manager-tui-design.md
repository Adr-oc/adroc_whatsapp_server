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

Install target: `pip install textual python-dotenv` (httpx already present)

---

## Configuration

On startup, load `ADMIN_API_KEY` and `MIDDLEWARE_URL` in order:

1. Environment variables already exported in shell
2. `.env` file in the current working directory (auto-detected via python-dotenv)
3. If neither found → show full-screen error with exact commands to fix

`MIDDLEWARE_URL` defaults to `http://localhost:8000` if not set.

---

## Middleware Change: `/api/logs` Endpoint

**New endpoint:** `GET /api/logs`
- Auth: `X-API-Key: ADMIN_API_KEY`
- Query params: `lines=100` (last N lines, default 100), `follow=true/false`
- Response: Server-Sent Events (SSE) stream when `follow=true`, plain JSON array when `follow=false`
- Implementation: tail the structlog output captured by uvicorn (read from a log buffer held in memory, ring buffer of last 1000 lines)
- The middleware already uses structlog — capture output to an in-memory deque in addition to stdout

---

## Screens

### Screen 1 — Dashboard (default on open)

**Layout:** 2-row grid — status cards row + tenants summary table

**Status cards (6, semaphore colors):**

| Card | Green | Yellow | Red |
|---|---|---|---|
| Middleware | `ok` | — | unreachable |
| Evolution API | `reachable` | — | unreachable |
| Database | `connected` | — | error |
| Active Tenants | any | — | 0 |
| Total Instances | any | — | — |
| Odoo Queue | 0 pending | 1–50 | >50 |

**Tenant summary table:** slug, display name, instance count, max instances, status

**Refresh:** Auto every 30 seconds. `R` forces immediate refresh. Last-refreshed timestamp shown bottom-right.

---

### Screen 2 — Tenants

**Layout:** Left table (70%) + right detail panel (30%)

**Table columns:** slug, display name, instances (n/max), status (semaphore dot)

**Navigation:** Arrow keys to move, table updates detail panel on selection change.

**Detail panel** (for selected tenant):
- slug, display name, Odoo webhook URL, max instances, created date
- Action buttons: Edit, Rotate API Key, Deactivate, View Instances

**Keyboard shortcuts:**
- `N` — open create tenant modal
- `E` — open edit tenant modal (pre-filled)
- `K` — rotate API key (confirm modal → show new key once, copyable)
- `D` — deactivate tenant (confirm modal)
- `Enter` — navigate to Instances screen filtered to this tenant
- `/` — inline search filter on table

**Create/Edit modal fields:** slug (create only), display name, Odoo webhook URL, Odoo API key, max instances

---

### Screen 3 — Instances

**Layout:** Filter bar + full-width table

**Filter bar:** Tenant dropdown (All / specific tenant). Updates table live.

**Table columns:**
- Instance name
- State (semaphore: green=open, yellow=connecting, red=closed/error)
- Phone number (or `—` if not connected)
- Tenant slug
- Last webhook (relative time of last event received, e.g. "2m ago" or `—`)

**Keyboard shortcuts:**
- `N` — create new instance (modal: select tenant, enter name)
- `R` — restart selected instance (confirm)
- `L` — logout selected instance (confirm)
- `Del` — delete selected instance (confirm)
- `/` — inline search filter
- `X` — export current table view (prompt: CSV or JSON, saved to `./instances-export-YYYYMMDD.csv/json`)

**Last webhook column:** sourced from `/api/health` pending_events + per-instance state update timestamps from connection status polling.

---

### Screen 4 — Logs

**Layout:** Full-width scrollable log panel

**Source:** `GET /api/logs?follow=true` — SSE stream

**Features:**
- New lines appended at bottom, auto-scrolls unless user scrolled up
- `F` — toggle between raw JSON and pretty-printed format
- `Space` — pause/resume auto-scroll
- `C` — clear display (does not affect server logs)
- Log level color coding: INFO=default, WARNING=yellow, ERROR=red
- Shows last 100 lines on connect, then live tail

---

### Screen 5 — Test Message

**Layout:** Centered form

**Flow:**
1. Select tenant (dropdown, populated from API)
2. Select instance (dropdown, filtered by tenant, shows state)
3. Enter phone number (text input, validated: digits only)
4. Enter message text (text area)
5. Send button (`Ctrl+Enter` shortcut)

**Result display:** Success → green banner with message ID. Error → red banner with error detail.

---

## Navigation & Global UX

**Sidebar (fixed left, ~160px):**
```
⚡ Adroc WA
─────────────
📊 Dashboard
🏢 Tenants
📱 Instancias
📋 Logs
💬 Test Mensaje
─────────────
● <status>
q Salir  ? Ayuda
```

- Click or `1-5` number keys to switch screens
- Active screen highlighted with left border accent

**Global shortcuts:**
| Key | Action |
|---|---|
| `1`–`5` | Switch screen |
| `Q` | Quit |
| `?` | Toggle help panel (overlay showing all shortcuts) |
| `R` | Refresh current screen |

**Error handling:**
- API errors show inline red banner with status code + message
- Network timeout → yellow warning banner, auto-retry once
- 403 Forbidden → red banner "Invalid admin key"

**Destructive confirmations:** Modal with action description + `Confirm` / `Cancel` buttons. Keyboard: `Enter` confirms, `Esc` cancels.

---

## File Structure

```
scripts/
└── manage.py    ← single file, replaces current manage.py entirely
```

No new files. No new directories (except `docs/superpowers/specs/` for this spec).

---

## Out of Scope

- Sending real WhatsApp messages from the TUI (Test Message is debug-only)
- Multi-user auth / role separation
- TUI theming / color customization
- Automated alerting / notifications
