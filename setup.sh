#!/usr/bin/env bash
set -euo pipefail

# ── Colors ──────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
RESET='\033[0m'

ok()   { echo -e "  ${GREEN}✓${RESET} $1"; }
warn() { echo -e "  ${YELLOW}!${RESET} $1"; }
fail() { echo -e "  ${RED}✗${RESET} $1"; exit 1; }

# ── Banner ──────────────────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}        ++++                            ++++${RESET}"
echo -e "${CYAN}       +++++++++                    +++++++++${RESET}"
echo -e "${CYAN}       ++++++++++++              ++++++++++++${RESET}"
echo -e "${CYAN}       ++++++++++++++++++++++++++++++++++++++${RESET}"
echo -e "${CYAN}       ++++++++++++++++++++++++++++++++++++++${RESET}"
echo -e "${CYAN}       ++++++++++++++++++++++++++++++++++++++${RESET}"
echo -e "${CYAN}       ++++++++++++++++++++++++++++++++++++++${RESET}"
echo -e "${CYAN}       ++++++++++++++++++++++++++++++++++++++${RESET}"
echo -e "${CYAN}      +++++++++++   ++++++++++++   +++++++++++${RESET}"
echo -e "${CYAN}     +++++++++        ++++++++        +++++++++${RESET}"
echo -e "${CYAN}    ++++++++      ++    ++++    +++      +++++++${RESET}"
echo -e "${CYAN}  +++++++      +++++    +++++    ++++       ++++++${RESET}"
echo -e "${CYAN}  ++++++        ++++   ++++++    ++++       ++++++${RESET}"
echo -e "${CYAN}    ++++++         +  ++++++++  ++        ++++++${RESET}"
echo -e "${CYAN}      ++++++         ++++++++++         ++++++${RESET}"
echo -e "${CYAN}        ++++++      ++++    +++++     ++++++${RESET}"
echo -e "${CYAN}          ++++++  ++++++    +++++++ ++++++${RESET}"
echo -e "${CYAN}            ++++++++++++++++++++++++++++${RESET}"
echo -e "${CYAN}              ++++++++++++++++++++++++${RESET}"
echo -e "${CYAN}                  ++++++++++++++++${RESET}"
echo -e "${CYAN}                      +++++++++${RESET}"
echo ""
echo -e "  ${BOLD}Adroc WhatsApp Server${RESET}  ${DIM}— setup${RESET}"
echo ""

# ── Prerequisites ───────────────────────────────────────────────────────────
echo -e "${BOLD}  Checking prerequisites${RESET}"

command -v docker >/dev/null 2>&1 || fail "Docker is not installed"
ok "Docker"

if docker compose version >/dev/null 2>&1; then
    COMPOSE_CMD="docker compose"
    ok "Docker Compose (v2)"
elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE_CMD="docker-compose"
    ok "Docker Compose (v1)"
else
    fail "Docker Compose is not installed"
fi

command -v openssl >/dev/null 2>&1 || fail "openssl is not installed"
ok "OpenSSL"

command -v nginx >/dev/null 2>&1 || fail "nginx is not installed"
ok "Nginx"

command -v curl >/dev/null 2>&1 || fail "curl is not installed"
ok "curl"

# ── Detect server IP ───────────────────────────────────────────────────────
SERVER_IP=$(hostname -I | awk '{print $1}')
echo ""
ok "Server IP detected: ${CYAN}${SERVER_IP}${RESET}"

# ── Configure .env ──────────────────────────────────────────────────────────
echo ""
if [ -f .env ]; then
    echo -e "  ${DIM}Existing .env found.${RESET}"
    echo -n "  Overwrite? (y/N): "
    read -r OVERWRITE
    if [[ ! "$OVERWRITE" =~ ^[Yy]$ ]]; then
        ok "Keeping existing .env"
        SKIP_ENV=1
    else
        SKIP_ENV=0
    fi
else
    SKIP_ENV=0
fi

if [ "${SKIP_ENV:-0}" = "0" ]; then
    echo -e "${BOLD}  Configuration${RESET}"
    echo ""

    echo -n "  Odoo webhook URL: "
    read -r ODOO_WEBHOOK_URL
    while [ -z "$ODOO_WEBHOOK_URL" ]; do
        warn "Required. Example: https://company.odoo.com/whatsapp/webhook"
        echo -n "  Odoo webhook URL: "
        read -r ODOO_WEBHOOK_URL
    done

    echo -n "  PostgreSQL username [adroc]: "
    read -r POSTGRES_USER
    POSTGRES_USER=${POSTGRES_USER:-adroc}

    # Generate secrets
    POSTGRES_PASSWORD=$(openssl rand -hex 16)
    EVOLUTION_API_KEY=$(openssl rand -hex 32)
    MIDDLEWARE_API_KEY=$(openssl rand -hex 32)
    ODOO_API_KEY=$(openssl rand -hex 32)

    cat > .env <<EOF
POSTGRES_USER=${POSTGRES_USER}
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
EVOLUTION_DB_NAME=evolution
MIDDLEWARE_DB_NAME=middleware
EVOLUTION_API_KEY=${EVOLUTION_API_KEY}
MIDDLEWARE_API_KEY=${MIDDLEWARE_API_KEY}
ODOO_WEBHOOK_URL=${ODOO_WEBHOOK_URL}
ODOO_API_KEY=${ODOO_API_KEY}
EOF

    ok "Created .env"
    echo ""
    echo -e "  ${BOLD}Save these keys for Odoo:${RESET}"
    echo -e "    MIDDLEWARE_API_KEY = ${CYAN}${MIDDLEWARE_API_KEY}${RESET}"
    echo -e "    ODOO_API_KEY      = ${CYAN}${ODOO_API_KEY}${RESET}"
    echo ""
fi

# ── Start services ──────────────────────────────────────────────────────────
echo -e "${BOLD}  Starting services${RESET}"
echo -e "  ${DIM}(first run may take a few minutes pulling images)${RESET}"
$COMPOSE_CMD up -d --build 2>&1 | while IFS= read -r line; do
    echo -e "  ${DIM}${line}${RESET}"
done

# ── Wait for health ─────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}  Waiting for services to be ready${RESET}"
MAX_WAIT=90
ELAPSED=0
HEALTH_URL="http://localhost:8000/api/health"

while [ $ELAPSED -lt $MAX_WAIT ]; do
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$HEALTH_URL" 2>/dev/null || echo "000")
    if [ "$HTTP_CODE" = "200" ]; then
        break
    fi
    sleep 3
    ELAPSED=$((ELAPSED + 3))
    echo -ne "\r  ${DIM}Waiting... ${ELAPSED}s / ${MAX_WAIT}s${RESET}"
done
echo -ne "\r\033[2K"

if [ "$HTTP_CODE" != "200" ]; then
    fail "Middleware not responding after ${MAX_WAIT}s. Check: ${COMPOSE_CMD} logs middleware"
fi

HEALTH=$(curl -s "$HEALTH_URL" 2>/dev/null)
ok "Middleware healthy"

if echo "$HEALTH" | grep -q '"database":"connected"'; then
    ok "PostgreSQL connected"
else
    warn "PostgreSQL not connected"
fi

if echo "$HEALTH" | grep -q '"evolution_api":"reachable"'; then
    ok "Evolution API reachable"
else
    warn "Evolution API not reachable yet (may still be starting)"
fi

# ── Setup nginx ─────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}  Configuring nginx${RESET}"

NGINX_CONF="/etc/nginx/sites-available/adroc_whatsapp.conf"

cat > "$NGINX_CONF" <<EOF
upstream adroc_whatsapp_middleware {
    server 127.0.0.1:8000;
}

server {
    listen 80;
    server_name ${SERVER_IP};

    location / {
        proxy_pass http://adroc_whatsapp_middleware;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF

# Enable site (create symlink if not exists)
ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/adroc_whatsapp.conf

# Test and reload nginx
if nginx -t 2>/dev/null; then
    systemctl reload nginx
    ok "Nginx configured and reloaded"
else
    fail "Nginx config test failed. Check: nginx -t"
fi

# ── Verify end-to-end ──────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}  Verifying end-to-end${RESET}"
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://${SERVER_IP}/api/health" 2>/dev/null || echo "000")

if [ "$HTTP_CODE" = "200" ]; then
    ok "http://${SERVER_IP}/api/health returns 200"
else
    warn "http://${SERVER_IP}/api/health returned HTTP ${HTTP_CODE}"
fi

# ── Done ────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}  Setup complete${RESET}"
echo ""
echo -e "  ${DIM}Middleware URL for Odoo:${RESET} ${CYAN}http://${SERVER_IP}${RESET}"
echo ""
echo -e "  ${DIM}Useful commands:${RESET}"
echo -e "    Status:   ${CYAN}${COMPOSE_CMD} ps${RESET}"
echo -e "    Logs:     ${CYAN}${COMPOSE_CMD} logs -f middleware${RESET}"
echo -e "    Restart:  ${CYAN}${COMPOSE_CMD} restart${RESET}"
echo ""
