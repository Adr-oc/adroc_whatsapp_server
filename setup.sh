#!/usr/bin/env bash
set -euo pipefail

# ── Colors ───────────────────────────────────────────────────────────────────
BOLD='\033[1m'
DIM='\033[2m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
RESET='\033[0m'

ok()   { echo -e "  ${GREEN}✓${RESET} $1"; }
warn() { echo -e "  ${YELLOW}!${RESET} $1"; }
fail() { echo -e "  ${RED}✗${RESET} $1"; exit 1; }
ask()  { echo -en "  ${CYAN}?${RESET} $1"; }

header() {
    echo ""
    echo -e "${BOLD}  $1${RESET}"
    echo -e "${DIM}  $(printf '%.0s─' $(seq 1 ${#1}))${RESET}"
}

# Restore cursor on exit/interrupt
cleanup() { echo -ne "\033[?25h"; }
trap cleanup EXIT

# ── Arrow-key selector ───────────────────────────────────────────────────────
# Usage: select_menu "Prompt" "Option A" "Option B" ...
# Returns selected index in $REPLY_IDX and label in $REPLY_VAL
select_menu() {
    local prompt=$1; shift
    local options=("$@")
    local count=${#options[@]}
    local selected=0

    ask "$prompt"
    echo ""

    echo -ne "\033[?25l"  # hide cursor

    for i in "${!options[@]}"; do
        if [ "$i" -eq $selected ]; then
            echo -e "    ${CYAN}❯${RESET} ${BOLD}${options[$i]}${RESET}"
        else
            echo -e "      ${DIM}${options[$i]}${RESET}"
        fi
    done

    while true; do
        IFS= read -rsn1 key
        if [[ $key == $'\x1b' ]]; then
            read -rsn2 arrow
            case $arrow in
                '[A') ((selected = selected > 0 ? selected - 1 : count - 1)) ;;
                '[B') ((selected = selected < count - 1 ? selected + 1 : 0)) ;;
            esac
        elif [[ $key == '' ]]; then
            break
        fi

        # Redraw
        echo -ne "\033[${count}A"
        for i in "${!options[@]}"; do
            echo -ne "\033[2K"
            if [ "$i" -eq $selected ]; then
                echo -e "    ${CYAN}❯${RESET} ${BOLD}${options[$i]}${RESET}"
            else
                echo -e "      ${DIM}${options[$i]}${RESET}"
            fi
        done
    done

    echo -ne "\033[?25h"  # show cursor

    # Replace menu with selection
    echo -ne "\033[$((count + 1))A"
    echo -ne "\033[2K"
    echo -e "  ${CYAN}?${RESET} ${prompt}${BOLD}${options[$selected]}${RESET}"
    for ((i = 0; i < count; i++)); do
        echo -ne "\033[2K\n"
    done
    echo -ne "\033[${count}A"

    REPLY_IDX=$selected
    REPLY_VAL="${options[$selected]}"
}

# Convenience: yes/no selector
confirm() {
    local prompt=$1
    local default=${2:-0}  # 0=Yes first, 1=No first
    if [ "$default" -eq 0 ]; then
        select_menu "$prompt" "Yes" "No"
    else
        select_menu "$prompt" "No" "Yes"
    fi
    if [ "$default" -eq 0 ]; then
        return $REPLY_IDX  # 0=Yes=success, 1=No=failure
    else
        [ "$REPLY_IDX" -eq 1 ]  # 1=Yes=success
    fi
}

# ── Banner ───────────────────────────────────────────────────────────────────
clear
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
echo -e "  ${BOLD}adroc whatsapp server${RESET}  ${DIM}─${RESET}  ${DIM}installer${RESET}"
echo ""

# ── Prerequisites ────────────────────────────────────────────────────────────
header "Checking prerequisites"

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

command -v openssl >/dev/null 2>&1 || fail "openssl is not installed (needed for key generation)"
ok "OpenSSL"

# ── Main menu ────────────────────────────────────────────────────────────────
echo ""
select_menu "What would you like to do? " \
    "Full setup          Configure .env, launch, verify" \
    "Launch only         Start services with existing .env" \
    "Run tests           Execute the test suite" \
    "Health check        Check if services are running" \
    "Generate nginx conf Create nginx reverse proxy config"

ACTION=$REPLY_IDX

# ── Action: Health check ─────────────────────────────────────────────────────
do_health_check() {
    header "Health check"
    HEALTH_URL="http://localhost:8000/api/health"
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$HEALTH_URL" 2>/dev/null || echo "000")

    if [ "$HTTP_CODE" = "200" ]; then
        HEALTH=$(curl -s "$HEALTH_URL" 2>/dev/null)
        ok "Middleware responding (HTTP 200)"

        if echo "$HEALTH" | grep -q '"database":"connected"'; then
            ok "PostgreSQL connected"
        else
            warn "PostgreSQL not connected"
        fi

        if echo "$HEALTH" | grep -q '"evolution_api":"reachable"'; then
            ok "Evolution API reachable"
        else
            warn "Evolution API unreachable"
        fi
    else
        warn "Middleware not responding (HTTP $HTTP_CODE)"
        echo -e "  ${DIM}Is it running? Try: ${COMPOSE_CMD} ps${RESET}"
    fi
}

# ── Action: Run tests ────────────────────────────────────────────────────────
do_run_tests() {
    header "Running tests"

    if ! command -v pip >/dev/null 2>&1 && ! command -v pip3 >/dev/null 2>&1; then
        fail "pip not found — need Python + pip to run tests"
    fi

    PIP_CMD=$(command -v pip3 2>/dev/null || command -v pip)
    echo -e "  ${DIM}Installing test dependencies...${RESET}"
    $PIP_CMD install -q -r middleware/requirements-dev.txt 2>&1 | tail -1

    echo -e "  ${DIM}Running pytest...${RESET}"
    echo ""
    if python -m pytest middleware/tests/ -v --tb=short; then
        echo ""
        ok "All tests passed"
    else
        echo ""
        warn "Some tests failed — check output above"
    fi
}

# ── Action: Launch services ──────────────────────────────────────────────────
do_launch() {
    if [ ! -f .env ]; then
        fail "No .env file found. Run 'Full setup' first."
    fi

    header "Starting services"
    echo -e "  ${DIM}This may take a few minutes on first run (pulling images)...${RESET}"
    $COMPOSE_CMD up -d --build 2>&1 | while IFS= read -r line; do
        echo -e "  ${DIM}${line}${RESET}"
    done

    header "Waiting for services"
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

    if [ "$HTTP_CODE" = "200" ]; then
        HEALTH=$(curl -s "$HEALTH_URL" 2>/dev/null)
        ok "Middleware healthy"

        if echo "$HEALTH" | grep -q '"database":"connected"'; then
            ok "PostgreSQL connected"
        else
            warn "PostgreSQL not connected (check logs)"
        fi

        if echo "$HEALTH" | grep -q '"evolution_api":"reachable"'; then
            ok "Evolution API reachable"
        else
            warn "Evolution API not reachable yet (may still be starting)"
        fi
    else
        warn "Middleware not responding after ${MAX_WAIT}s"
        echo -e "  ${DIM}Check logs: ${COMPOSE_CMD} logs middleware${RESET}"
    fi
}

# ── Action: Full setup (configure .env) ──────────────────────────────────────
do_configure() {
    # Check for existing .env
    if [ -f .env ]; then
        echo ""
        if ! confirm "Existing .env found. Overwrite? " 1; then
            echo -e "  ${DIM}Keeping existing .env${RESET}"
            return 0
        fi
    fi

    header "Configuration"

    ask "Odoo webhook URL: "
    read -r ODOO_WEBHOOK_URL
    while [ -z "$ODOO_WEBHOOK_URL" ]; do
        warn "Required. Example: https://company.odoo.com/whatsapp/webhook"
        ask "Odoo webhook URL: "
        read -r ODOO_WEBHOOK_URL
    done

    ask "PostgreSQL username ${DIM}[adroc]${RESET}: "
    read -r POSTGRES_USER
    POSTGRES_USER=${POSTGRES_USER:-adroc}

    EVOLUTION_DB_NAME="evolution"
    MIDDLEWARE_DB_NAME="middleware"

    header "Generating secrets"

    POSTGRES_PASSWORD=$(openssl rand -hex 16)
    ok "POSTGRES_PASSWORD"

    EVOLUTION_API_KEY=$(openssl rand -hex 32)
    ok "EVOLUTION_API_KEY"

    MIDDLEWARE_API_KEY=$(openssl rand -hex 32)
    ok "MIDDLEWARE_API_KEY"

    ODOO_API_KEY=$(openssl rand -hex 32)
    ok "ODOO_API_KEY"

    header "Writing .env"

    cat > .env <<EOF
POSTGRES_USER=${POSTGRES_USER}
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
EVOLUTION_DB_NAME=${EVOLUTION_DB_NAME}
MIDDLEWARE_DB_NAME=${MIDDLEWARE_DB_NAME}
EVOLUTION_API_KEY=${EVOLUTION_API_KEY}
MIDDLEWARE_API_KEY=${MIDDLEWARE_API_KEY}
ODOO_WEBHOOK_URL=${ODOO_WEBHOOK_URL}
ODOO_API_KEY=${ODOO_API_KEY}
EOF

    ok "Created .env"
    echo ""
    echo -e "  ${DIM}Save these keys for Odoo configuration:${RESET}"
    echo -e "    MIDDLEWARE_API_KEY = ${CYAN}${MIDDLEWARE_API_KEY}${RESET}"
    echo -e "    ODOO_API_KEY      = ${CYAN}${ODOO_API_KEY}${RESET}"
}

# ── Action: Generate nginx config ────────────────────────────────────────────
do_nginx_conf() {
    header "Nginx reverse proxy config"

    ask "Public host (domain or IP) for middleware (e.g. whatsapp.example.com or ${CYAN}193.46.198.255${RESET}): "
    read -r PUBLIC_HOST
    while [ -z "$PUBLIC_HOST" ]; do
        warn "Required. This is what users/Odoo will call."
        ask "Public host: "
        read -r PUBLIC_HOST
    done

    ask "Public port [80]: "
    read -r PUBLIC_PORT
    PUBLIC_PORT=${PUBLIC_PORT:-80}

    CONFIG_FILE="nginx-adroc-whatsapp.conf"

    cat > "$CONFIG_FILE" <<EOF
upstream adroc_whatsapp_middleware {
    server 127.0.0.1:8000;
}

server {
    listen ${PUBLIC_PORT};
    server_name ${PUBLIC_HOST};

    # Optional: redirect /api/health quickly
    location /api/health {
        proxy_pass http://adroc_whatsapp_middleware/api/health;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location / {
        proxy_pass http://adroc_whatsapp_middleware;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF

    ok "Written nginx config to ./$CONFIG_FILE"
    echo ""
    echo -e "  ${DIM}To enable it on a Linux server with nginx:${RESET}"
    echo -e "    1. Copy it:   ${CYAN}sudo cp $CONFIG_FILE /etc/nginx/sites-available/adroc_whatsapp.conf${RESET}"
    echo -e "    2. Enable it: ${CYAN}sudo ln -s /etc/nginx/sites-available/adroc_whatsapp.conf /etc/nginx/sites-enabled/${RESET}"
    echo -e "    3. Test:      ${CYAN}sudo nginx -t${RESET}"
    echo -e "    4. Reload:    ${CYAN}sudo systemctl reload nginx${RESET}"
    echo ""
    echo -e "  ${DIM}Then set in Odoo:${RESET}"
    echo -e "    whatsapp.middleware_url = ${CYAN}http://$PUBLIC_HOST${PUBLIC_PORT:+:$PUBLIC_PORT}${RESET}"
}

# ── Dispatch ─────────────────────────────────────────────────────────────────
case $ACTION in
    0) # Full setup
        do_configure

        echo ""
        if confirm "Start services now? "; then
            do_launch

            echo ""
            if confirm "Run test suite? " 1; then
                do_run_tests
            fi
        fi
        ;;

    1) # Launch only
        do_launch
        ;;

    2) # Run tests
        do_run_tests
        ;;

    3) # Health check
        do_health_check
        ;;

    4) # Generate nginx config
        do_nginx_conf
        ;;
esac

# ── Done ─────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}  Done${RESET}"
echo ""
echo -e "  ${DIM}Useful commands:${RESET}"
echo -e "    Status:   ${CYAN}${COMPOSE_CMD} ps${RESET}"
echo -e "    Logs:     ${CYAN}${COMPOSE_CMD} logs -f middleware${RESET}"
echo -e "    Tests:    ${CYAN}cd middleware && python -m pytest tests/ -v${RESET}"
echo -e "    Restart:  ${CYAN}${COMPOSE_CMD} restart${RESET}"
echo ""
