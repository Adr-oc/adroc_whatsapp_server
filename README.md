# adroc_whatsapp_server

> Backend server for the adroc_whatsapp ecosystem. Handles WhatsApp connectivity via Evolution API, message persistence, and communication with Odoo.

**Companion repo:** [`adroc_whatsapp`](https://github.com/Adr-oc/adroc_whatsapp) — Odoo 19 module that receives webhooks from this server and provides the business UI.

---

## What This Is

A Docker-based server stack that connects WhatsApp to Odoo through three services:

1. **Evolution API** — Manages WhatsApp sessions (QR pairing, send/receive messages)
2. **Middleware (FastAPI)** — API gateway that forwards webhooks to Odoo with retry, handles instance management
3. **PostgreSQL** — Backup database for disaster recovery

```
[WhatsApp Users]
       ↕
[Evolution API :8080]
       ↕ webhooks
[FastAPI Middleware :8000] ←→ [Odoo.sh via HTTP]
       ↕
[PostgreSQL :5432]
```

---

## Quick Start

### Prerequisites

- Docker + Docker Compose v2
- A server with ports 8080 and 8000 available
- An Odoo.sh instance with the [`adroc_whatsapp`](https://github.com/Adr-oc/adroc_whatsapp) module installed

### Interactive installer (recommended)

```bash
git clone https://github.com/Adr-oc/adroc_whatsapp_server.git
cd adroc_whatsapp_server
chmod +x setup.sh
./setup.sh
```

The installer will:

- Check prerequisites (Docker, Compose, OpenSSL)
- Ask for your Odoo webhook URL
- Auto-generate all API keys and secrets
- Create the `.env` file
- Optionally start all services and verify health
- Optionally run the test suite (62 tests)

### Manual setup

If you prefer to configure manually:

```bash
git clone https://github.com/Adr-oc/adroc_whatsapp_server.git
cd adroc_whatsapp_server
cp .env.example .env
```

Generate API keys (`openssl rand -hex 32`, run 3 times) and edit `.env`:

```env
POSTGRES_USER=adroc
POSTGRES_PASSWORD=<generated>
EVOLUTION_DB_NAME=evolution
MIDDLEWARE_DB_NAME=middleware
EVOLUTION_API_KEY=<generated>
MIDDLEWARE_API_KEY=<generated>
ODOO_WEBHOOK_URL=https://your-instance.odoo.com/whatsapp/webhook
ODOO_API_KEY=<generated>
```

Then launch:

```bash
docker compose up -d
curl http://localhost:8000/api/health
```

> **Important:** The `ODOO_API_KEY` must also be configured in Odoo so the module can validate incoming requests. The `MIDDLEWARE_API_KEY` must be configured in Odoo so it can authenticate when calling this server.

---

## How Messages Flow

**Incoming (WhatsApp to Odoo):**
```
WhatsApp user sends message
  → Evolution API receives it
  → Evolution sends webhook to middleware (POST /webhooks/evolution)
  → Middleware forwards to Odoo (POST /whatsapp/webhook) with exponential backoff retry
  → Odoo processes and displays in Discuss
```

**Outgoing (Odoo to WhatsApp):**
```
Odoo agent clicks reply in Discuss
  → Odoo calls middleware (POST /api/instances/{name}/send with X-API-Key)
  → Middleware calls Evolution API (POST /message/sendText/{name})
  → Evolution sends via WhatsApp
```

---

## API Endpoints

All endpoints (except webhooks and health) require `X-API-Key` header.

| Method | Endpoint | Description | Called by |
|--------|----------|-------------|-----------|
| GET | `/api/health` | Health check | Anyone |
| POST | `/webhooks/evolution` | Receives Evolution events | Evolution API |
| POST | `/api/instances` | Create WhatsApp instance | Odoo |
| GET | `/api/instances` | List all instances | Odoo |
| GET | `/api/instances/{name}/qr` | Get QR code (base64) | Odoo |
| GET | `/api/instances/{name}/status` | Connection state | Odoo |
| DELETE | `/api/instances/{name}` | Remove instance | Odoo |
| PUT | `/api/instances/{name}/restart` | Restart instance | Odoo |
| DELETE | `/api/instances/{name}/logout` | Disconnect WhatsApp | Odoo |
| POST | `/api/instances/{name}/send` | Send message | Odoo |
| POST | `/api/resync` | Disaster recovery resync | Admin |

---

## Testing

```bash
cd middleware
pip install -r requirements-dev.txt
python -m pytest tests/ -v
```

62 tests covering schemas, services (Evolution API, Odoo forwarder with retry), all routes, and auth.

---

## Disaster Recovery

If Odoo.sh is restored from a backup and messages are lost:

```bash
# Using the CLI script
python scripts/resync.py --from-date 2026-02-20T00:00:00Z --api-key YOUR_KEY --poll

# Or directly via API
curl -X POST http://localhost:8000/api/resync \
  -H "X-API-Key: your-middleware-key" \
  -H "Content-Type: application/json" \
  -d '{"from_date": "2026-02-20T00:00:00Z"}'
```

---

## Configuration Reference

| Variable | Description | Example |
|----------|-------------|---------|
| `POSTGRES_USER` | PostgreSQL username | `adroc` |
| `POSTGRES_PASSWORD` | PostgreSQL password | `strong-password` |
| `EVOLUTION_DB_NAME` | Database for Evolution API | `evolution` |
| `MIDDLEWARE_DB_NAME` | Database for middleware | `middleware` |
| `EVOLUTION_API_KEY` | Auth key for Evolution API | `openssl rand -hex 32` |
| `MIDDLEWARE_API_KEY` | Auth key Odoo uses to call middleware | `openssl rand -hex 32` |
| `ODOO_WEBHOOK_URL` | Odoo's webhook URL | `https://company.odoo.com/whatsapp/webhook` |
| `ODOO_API_KEY` | Auth key middleware uses to call Odoo | `openssl rand -hex 32` |

---

## Connecting to the Odoo Module

After deploying both repos, configure Odoo:

1. **Settings > Technical > System Parameters:**
   - `whatsapp.middleware_url` = `http://your-server:8000`
   - `whatsapp.middleware_api_key` = same as `MIDDLEWARE_API_KEY`
   - `whatsapp.odoo_api_key` = same as `ODOO_API_KEY`

2. **WhatsApp > Instances > Create** to pair your first number via QR.

---

## Tech Stack

- **Evolution API** — `evoapicloud/evolution-api:v2.3.7`
- **Python 3.11+** — FastAPI, SQLAlchemy 2.0 (async), httpx, Pydantic v2
- **PostgreSQL 16**
- **Docker Compose**

---

## License

Adroc — All rights reserved.
