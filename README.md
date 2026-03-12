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

Generate API keys (`openssl rand -hex 32`, run twice) and edit `.env`:

```env
POSTGRES_USER=adroc
POSTGRES_PASSWORD=<generated>
EVOLUTION_DB_NAME=evolution
MIDDLEWARE_DB_NAME=middleware
EVOLUTION_API_KEY=<generated>
ADMIN_API_KEY=<generated>
```

Then launch:

```bash
docker compose up -d
curl http://localhost:8000/api/health
```

> **Important:** After starting services, use `manage.py tenants create` to register your Odoo instance. The `odoo-api-key` you pass there is the shared secret between this middleware and Odoo.

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

## CLI Manager (`scripts/manage.py`)

The manager is the primary tool for administering tenants and instances after setup. It requires Python and `httpx` installed locally (`pip install httpx`) or (`sudo apt install python3-httpx`).

### Environment variables

```bash
export MIDDLEWARE_URL=http://localhost:8000   # default
export ADMIN_API_KEY=<your-admin-api-key>     # from setup / .env
export TENANT_API_KEY=<tenant-api-key>        # from tenants create
```

---

### Health check

```bash
python scripts/manage.py health
```

---

### Tenant management (requires `ADMIN_API_KEY`)

**List all tenants:**
```bash
python scripts/manage.py tenants --admin-key $ADMIN_API_KEY list
```

**Create a tenant** — returns a one-time API key, save it immediately:
```bash
python scripts/manage.py tenants --admin-key $ADMIN_API_KEY create \
  acme \
  "Acme Corp" \
  https://acme.odoo.com/whatsapp/webhook \
  <odoo-api-key>
```
> The `odoo-api-key` is the secret Odoo sends in the `X-API-Key` header when calling this middleware.

**Get tenant details:**
```bash
python scripts/manage.py tenants --admin-key $ADMIN_API_KEY get acme
```

**Update tenant:**
```bash
python scripts/manage.py tenants --admin-key $ADMIN_API_KEY update acme \
  --display-name "Acme Inc" \
  --max-instances 20
```

**Deactivate / reactivate:**
```bash
python scripts/manage.py tenants --admin-key $ADMIN_API_KEY deactivate acme
python scripts/manage.py tenants --admin-key $ADMIN_API_KEY update acme --activate
```

**Rotate API key** (invalidates the old key immediately):
```bash
python scripts/manage.py tenants --admin-key $ADMIN_API_KEY rotate-key acme
```

---

### Instance management (requires tenant `API_KEY`)

**List instances:**
```bash
python scripts/manage.py instances --tenant-key $TENANT_API_KEY list
```

**Create an instance** (one per WhatsApp number):
```bash
python scripts/manage.py instances --tenant-key $TENANT_API_KEY create ventas
```

**Get QR code for pairing** — scan in WhatsApp to connect:
```bash
# Print base64 info
python scripts/manage.py instances --tenant-key $TENANT_API_KEY qr ventas

# Save as image
python scripts/manage.py instances --tenant-key $TENANT_API_KEY qr ventas --save qr.png
```

**Check status:**
```bash
python scripts/manage.py instances --tenant-key $TENANT_API_KEY status ventas
```

**Restart / logout / delete:**
```bash
python scripts/manage.py instances --tenant-key $TENANT_API_KEY restart ventas
python scripts/manage.py instances --tenant-key $TENANT_API_KEY logout ventas
python scripts/manage.py instances --tenant-key $TENANT_API_KEY delete ventas
```

---

### Send a test message

```bash
python scripts/manage.py send --tenant-key $TENANT_API_KEY ventas 502XXXXXXXX "Hello from manager"
```

---

### First-run workflow

```
1. ./setup.sh                          → generates ADMIN_API_KEY, starts services
2. manage.py health                    → verify services are up
3. manage.py tenants create ...        → create tenant, save TENANT_API_KEY
4. manage.py instances create ventas  → create instance
5. manage.py instances qr ventas      → scan QR in WhatsApp
6. manage.py instances status ventas  → verify state = "open"
```

---

## API Endpoints

All endpoints (except webhooks and health) require `X-API-Key` header.

| Method | Endpoint | Description | Called by |
|--------|----------|-------------|-----------|
| GET | `/api/health` | Health check | Anyone |
| POST | `/webhooks/evolution` | Receives Evolution events | Evolution API |
| GET | `/api/admin/tenants` | List tenants | Admin |
| POST | `/api/admin/tenants` | Create tenant | Admin |
| GET | `/api/admin/tenants/{slug}` | Get tenant | Admin |
| PATCH | `/api/admin/tenants/{slug}` | Update tenant | Admin |
| DELETE | `/api/admin/tenants/{slug}` | Deactivate tenant | Admin |
| POST | `/api/admin/tenants/{slug}/rotate-key` | Rotate API key | Admin |
| POST | `/api/instances` | Create WhatsApp instance | Odoo / Tenant |
| GET | `/api/instances` | List instances | Odoo / Tenant |
| GET | `/api/instances/{name}/qr` | Get QR code (base64) | Odoo / Tenant |
| GET | `/api/instances/{name}/status` | Connection state | Odoo / Tenant |
| DELETE | `/api/instances/{name}` | Remove instance | Odoo / Tenant |
| PUT | `/api/instances/{name}/restart` | Restart instance | Odoo / Tenant |
| DELETE | `/api/instances/{name}/logout` | Disconnect WhatsApp | Odoo / Tenant |
| POST | `/api/instances/{name}/send` | Send message | Odoo / Tenant |
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
| `ADMIN_API_KEY` | Admin key for tenant management via manager CLI | `openssl rand -hex 32` |

> **Note:** `ODOO_WEBHOOK_URL` and `ODOO_API_KEY` are now configured per-tenant via `manage.py tenants create`, not in `.env`.

---

## Connecting to the Odoo Module

After deploying both repos:

1. Create a tenant via the manager (see CLI Manager section above). The `odoo-api-key` argument becomes the `X-API-Key` the middleware attaches when calling Odoo, and also what Odoo must send when calling back.

2. **Settings > Technical > System Parameters in Odoo:**
   - `whatsapp.middleware_url` = `http://your-server:8000`
   - `whatsapp.middleware_api_key` = the tenant API key returned by `manage.py tenants create`
   - `whatsapp.odoo_api_key` = the `odoo-api-key` you passed to `manage.py tenants create`

3. **WhatsApp > Instances > Create** (or `manage.py instances create`) to pair your first number via QR.

---

## Tech Stack

- **Evolution API** — `evoapicloud/evolution-api:v2.3.7`
- **Python 3.11+** — FastAPI, SQLAlchemy 2.0 (async), httpx, Pydantic v2
- **PostgreSQL 16**
- **Docker Compose**

---

## License

Adroc — All rights reserved.
