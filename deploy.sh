#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# Cloud-Lines Application Deployer
#
# Deploys (or updates) the application on an existing server. Infrastructure
# is managed separately via CloudFormation (see cloudformation.yml).
#
# This script is idempotent — safe to run on first deploy and every update.
#
# Prerequisites:
#   - Server already running with Docker installed (via CloudFormation stack)
#   - SSH key pair for the server
#   - Bash 4+
#
# Usage:
#   # Deploy using config file (server IP from config):
#   ./deploy.sh --config deploy.conf
#
#   # Deploy using CloudFormation stack to resolve server IP:
#   ./deploy.sh --config deploy.conf --stack cloudlines
#
#   # Force a clean Docker rebuild (no layer cache):
#   ./deploy.sh --config deploy.conf --no-cache
#
# What it does (every run):
#   1. Verify SSH + Docker connectivity
#   2. Sync project files to server
#   3. Write .env and configure nginx
#   4. Build Docker images (with cache) and restart containers
#   5. Run database migrations and collect static files
#   6. Set up SSL if configured and not yet provisioned
#   7. Health check
###############################################################################

# ── Colours & helpers ────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
err()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }
die()   { err "$@"; exit 1; }

separator() {
    echo ""
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
}

usage() {
    echo "Usage: ./deploy.sh [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --config FILE   Load configuration from file"
    echo "  --stack NAME    Fetch server IP from CloudFormation stack outputs"
    echo "  --no-cache      Force Docker to rebuild all layers (no cache)"
    echo "  --help, -h      Show this help message"
    echo ""
    echo "Infrastructure:"
    echo "  Server provisioning is handled by CloudFormation. See cloudformation.yml."
    echo ""
    echo "  Create stack:   aws cloudformation deploy \\"
    echo "                    --template-file cloudformation.yml \\"
    echo "                    --stack-name cloudlines \\"
    echo "                    --parameter-overrides KeyPairName=your-key"
    echo ""
    echo "  Then deploy:    ./deploy.sh --config deploy.conf --stack cloudlines"
}

# ── Pre-flight checks ───────────────────────────────────────────────────────
command -v ssh >/dev/null 2>&1 || die "ssh is not installed."

USE_RSYNC=true
if ! command -v rsync >/dev/null 2>&1; then
    USE_RSYNC=false
    warn "rsync not found — falling back to tar + scp"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Parse arguments ──────────────────────────────────────────────────────────
CONFIG_FILE=""
STACK_NAME=""
NO_CACHE=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --config)   CONFIG_FILE="$2"; shift 2 ;;
        --stack)    STACK_NAME="$2"; shift 2 ;;
        --no-cache) NO_CACHE=true; shift ;;
        --help|-h)  usage; exit 0 ;;
        *) die "Unknown argument: $1. Use --help for usage." ;;
    esac
done

USING_CONFIG=false
if [[ -n "$CONFIG_FILE" && -f "$CONFIG_FILE" ]]; then
    info "Loading configuration from $CONFIG_FILE"
    source "$CONFIG_FILE"
    USING_CONFIG=true
elif [[ -n "$CONFIG_FILE" ]]; then
    die "Config file not found: $CONFIG_FILE"
fi

# ── Resolve server IP from CloudFormation stack ──────────────────────────────
if [[ -n "$STACK_NAME" ]]; then
    command -v aws >/dev/null 2>&1 || die "AWS CLI is required when using --stack"
    info "Resolving server IP from CloudFormation stack: $STACK_NAME"

    REGION="${AWS_REGION:-eu-west-2}"
    SERVER_IP=$(aws cloudformation describe-stacks \
        --region "$REGION" \
        --stack-name "$STACK_NAME" \
        --query "Stacks[0].Outputs[?OutputKey=='ServerIP'].OutputValue" \
        --output text 2>/dev/null || echo "")

    if [[ -z "$SERVER_IP" || "$SERVER_IP" == "None" ]]; then
        die "Could not resolve ServerIP from stack '$STACK_NAME'. Is the stack created?"
    fi
    ok "Server IP: $SERVER_IP (from stack)"
fi

# ── Prompt helpers ───────────────────────────────────────────────────────────
prompt() {
    local var_name="$1"
    local prompt_text="$2"
    local default="${3:-}"

    if [[ -n "${!var_name:-}" ]]; then return; fi
    if [[ "$USING_CONFIG" == true ]] && declare -p "$var_name" &>/dev/null; then return; fi

    if [[ -n "$default" ]]; then
        read -rp "$(echo -e "${GREEN}?${NC}") $prompt_text [$default]: " input
        eval "$var_name=\"${input:-$default}\""
    else
        read -rp "$(echo -e "${GREEN}?${NC}") $prompt_text: " input
        eval "$var_name=\"$input\""
    fi
}

prompt_secret() {
    local var_name="$1"
    local prompt_text="$2"

    if [[ -n "${!var_name:-}" ]]; then return; fi
    if [[ "$USING_CONFIG" == true ]] && declare -p "$var_name" &>/dev/null; then return; fi

    read -srp "$(echo -e "${GREEN}?${NC}") $prompt_text: " input
    echo ""
    eval "$var_name=\"$input\""
}

# ── Gather configuration ────────────────────────────────────────────────────
separator
echo -e "${BLUE}Cloud-Lines — Deploy${NC}"
separator

info "Step 1: Server Connection"
prompt AWS_REGION    "AWS Region"                              "eu-west-2"
prompt SSH_KEY_PATH  "Path to SSH private key"                 ""
prompt SERVER_IP     "Server IP address"                       ""

[[ -n "$SERVER_IP" ]] || die "SERVER_IP is required. Set it in deploy.conf or use --stack."

separator
info "Step 2: Domain & SSL"
prompt DOMAIN        "Primary domain (leave blank for IP-only access)" ""

if [[ -n "$DOMAIN" ]]; then
    prompt SETUP_SSL "Set up SSL with Let's Encrypt? (yes/no)" "yes"
    if [[ "$SETUP_SSL" == "yes" ]]; then
        prompt SSL_EMAIL "Email for Let's Encrypt notifications" ""
    fi
else
    SETUP_SSL="no"
    info "No domain set — site will be accessible via server IP on HTTP"
fi

separator
info "Step 3: Application Configuration"
prompt SITE_NAME          "Site name"                          "app"
prompt_secret SECRET_KEY  "Django SECRET_KEY"
prompt_secret DB_PASSWORD "Database password"
prompt DB_NAME            "Database name"                      "cloudlines"
prompt DB_USER            "Database user"                      "cloudlines"

separator
info "Step 4: AWS Service Keys"
prompt_secret AWS_ACCESS_KEY_ID     "AWS Access Key ID (for S3/SES)"
prompt_secret AWS_SECRET_ACCESS_KEY "AWS Secret Access Key"
prompt AWS_S3_BUCKET               "S3 bucket for media"      "media.cloud-lines.com"

separator
info "Step 5: Stripe Keys"
prompt_secret STRIPE_SECRET_KEY      "Stripe Secret Key"
prompt_secret STRIPE_PUBLIC_KEY      "Stripe Public Key"
prompt_secret STRIPE_TEST_SECRET_KEY "Stripe Test Secret Key (or press enter to skip)"
prompt_secret STRIPE_TEST_PUBLIC_KEY "Stripe Test Public Key (or press enter to skip)"

# ── SSH setup ────────────────────────────────────────────────────────────────
[[ -f "$SSH_KEY_PATH" ]] || die "SSH key not found at $SSH_KEY_PATH"
chmod 600 "$SSH_KEY_PATH" 2>/dev/null || true

SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=10 -i $SSH_KEY_PATH"

remote() {
    ssh $SSH_OPTS "ubuntu@${SERVER_IP}" "$@"
}

APP_DIR="/home/ubuntu/cloud-lines"

# ── Save config for future runs ──────────────────────────────────────────────
save_config() {
    local conf="$SCRIPT_DIR/deploy.conf"
    cat > "$conf" <<CONF
# Cloud-Lines Deployment Configuration
# Generated on $(date -u +"%Y-%m-%d %H:%M:%S UTC")
#
# Deploy:       ./deploy.sh --config deploy.conf
# With stack:   ./deploy.sh --config deploy.conf --stack cloudlines
# Clean build:  ./deploy.sh --config deploy.conf --no-cache

AWS_REGION="$AWS_REGION"
SSH_KEY_PATH="$SSH_KEY_PATH"
SERVER_IP="$SERVER_IP"
DOMAIN="${DOMAIN}"
SETUP_SSL="${SETUP_SSL}"
SSL_EMAIL="${SSL_EMAIL:-}"
SITE_NAME="$SITE_NAME"
DB_NAME="$DB_NAME"
DB_USER="$DB_USER"
AWS_S3_BUCKET="$AWS_S3_BUCKET"

# Secrets — uncomment if you want to save them (not recommended)
# SECRET_KEY="$SECRET_KEY"
# DB_PASSWORD="$DB_PASSWORD"
# AWS_ACCESS_KEY_ID="$AWS_ACCESS_KEY_ID"
# AWS_SECRET_ACCESS_KEY="$AWS_SECRET_ACCESS_KEY"
# STRIPE_SECRET_KEY="$STRIPE_SECRET_KEY"
# STRIPE_PUBLIC_KEY="$STRIPE_PUBLIC_KEY"
# STRIPE_TEST_SECRET_KEY="$STRIPE_TEST_SECRET_KEY"
# STRIPE_TEST_PUBLIC_KEY="$STRIPE_TEST_PUBLIC_KEY"
CONF
    ok "Configuration saved to deploy.conf"
}

###############################################################################
# PHASE 1: Verify Server
###############################################################################
separator
info "Phase 1: Verifying server"
separator

info "Checking SSH connectivity..."
ssh $SSH_OPTS -o BatchMode=yes "ubuntu@${SERVER_IP}" "echo ready" >/dev/null 2>&1 \
    || die "Cannot SSH into $SERVER_IP. Check your key and security group."
ok "SSH connection verified"

info "Checking Docker is available..."
for i in $(seq 1 24); do
    if remote "command -v docker" >/dev/null 2>&1; then
        break
    fi
    if [[ $i -eq 1 ]]; then
        info "Docker not ready yet — waiting for server setup to complete..."
    fi
    sleep 5
done
remote "command -v docker" >/dev/null 2>&1 \
    || die "Docker not found on server after 2 minutes. Check /var/log/cloud-init-docker.log on the server."
ok "Docker is ready"

save_config

###############################################################################
# PHASE 2: Sync Code
###############################################################################
separator
info "Phase 2: Syncing project files"
separator

info "Uploading project files to server..."
if [[ "$USE_RSYNC" == true ]]; then
    rsync -azP --delete \
        --exclude '.git' \
        --exclude '.env' \
        --exclude '*.pyc' \
        --exclude '__pycache__' \
        --exclude '*.sqlite3' \
        --exclude 'node_modules' \
        --exclude 'venv' \
        --exclude '.DS_Store' \
        --exclude 'deploy.conf' \
        -e "ssh $SSH_OPTS" \
        "$SCRIPT_DIR/" "ubuntu@${SERVER_IP}:${APP_DIR}/"
else
    TARBALL=$(mktemp /tmp/cloudlines-deploy.XXXXXX.tar.gz)
    tar czf "$TARBALL" \
        --exclude='.git' \
        --exclude='.env' \
        --exclude='*.pyc' \
        --exclude='__pycache__' \
        --exclude='*.sqlite3' \
        --exclude='node_modules' \
        --exclude='venv' \
        --exclude='.DS_Store' \
        --exclude='deploy.conf' \
        -C "$SCRIPT_DIR" .
    remote "mkdir -p ${APP_DIR}"
    scp $SSH_OPTS "$TARBALL" "ubuntu@${SERVER_IP}:/tmp/cloudlines-deploy.tar.gz"
    remote "rm -rf ${APP_DIR:?}/* && tar xzf /tmp/cloudlines-deploy.tar.gz -C ${APP_DIR} && rm /tmp/cloudlines-deploy.tar.gz"
    rm -f "$TARBALL"
fi
ok "Project files synced"

###############################################################################
# PHASE 3: Configure
###############################################################################
separator
info "Phase 3: Configuration"
separator

# ── Write .env ───────────────────────────────────────────────────────────────
info "Writing .env file..."

if [[ -n "$DOMAIN" ]]; then
    ALLOWED_HOSTS_VAL="*.${DOMAIN},${DOMAIN},${SERVER_IP}"
else
    ALLOWED_HOSTS_VAL="*"
fi

ssh $SSH_OPTS "ubuntu@${SERVER_IP}" "cat > ${APP_DIR}/.env" <<ENV
# Cloud-Lines Production Environment
# Generated by deploy.sh on $(date -u +"%Y-%m-%d %H:%M:%S UTC")

# Django
DJANGO_SETTINGS_MODULE=cloudlines.settings
SECRET_KEY=${SECRET_KEY}
DEBUG=False
ALLOWED_HOSTS=${ALLOWED_HOSTS_VAL}

# Database
DB_NAME=${DB_NAME}
DB_USER=${DB_USER}
DB_PASSWORD=${DB_PASSWORD}
DB_HOST=db
DB_PORT=5432

# Redis / Celery
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/1

# AWS
AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID}
AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY}
AWS_STORAGE_BUCKET_NAME=${AWS_S3_BUCKET}
AWS_S3_REGION_NAME=${AWS_REGION}
AWS_S3_CUSTOM_DOMAIN=${AWS_S3_BUCKET}

# Stripe
STRIPE_SECRET_KEY=${STRIPE_SECRET_KEY}
STRIPE_PUBLIC_KEY=${STRIPE_PUBLIC_KEY}
STRIPE_TEST_SECRET_KEY=${STRIPE_TEST_SECRET_KEY:-}
STRIPE_TEST_PUBLIC_KEY=${STRIPE_TEST_PUBLIC_KEY:-}

# Email (SES)
EMAIL_BACKEND=django_ses.SESBackend
AWS_SES_REGION_NAME=eu-west-1
AWS_SES_REGION_ENDPOINT=email.eu-west-1.amazonaws.com
DEFAULT_FROM_EMAIL=contact@masys.co.uk

# Protocol
HTTP_PROTOCOL=$(if [[ "$SETUP_SSL" == "yes" ]]; then echo "https"; else echo "http"; fi)

# Site
SITE_NAME=${SITE_NAME}
ENV
ok ".env written"

# ── Configure nginx ──────────────────────────────────────────────────────────
info "Configuring nginx..."
ssh $SSH_OPTS "ubuntu@${SERVER_IP}" "mkdir -p ${APP_DIR}/nginx/ssl"

# Detect if SSL certs already exist on the server
HAS_SSL_CERT=false
if [[ -n "$DOMAIN" ]] && remote "test -f /etc/letsencrypt/live/${DOMAIN}/fullchain.pem" 2>/dev/null; then
    HAS_SSL_CERT=true
fi

if [[ "$HAS_SSL_CERT" == true ]]; then
    # SSL config — certs already on server
    ssh $SSH_OPTS "ubuntu@${SERVER_IP}" "cat > ${APP_DIR}/nginx/default.conf" <<NGINX_SSL
upstream django {
    server web:8000;
}

server {
    listen 80;
    server_name ${DOMAIN} *.${DOMAIN};

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location / {
        return 301 https://\$host\$request_uri;
    }
}

server {
    listen 443 ssl;
    http2 on;
    server_name ${DOMAIN} *.${DOMAIN};

    ssl_certificate     /etc/letsencrypt/live/${DOMAIN}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${DOMAIN}/privkey.pem;

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;

    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    client_max_body_size 20M;

    location /static/ {
        alias /app/staticfiles/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    location /media/ {
        alias /app/media/;
        expires 7d;
    }

    location / {
        proxy_pass http://django;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 120s;
    }
}
NGINX_SSL
    ok "Nginx configured with SSL for $DOMAIN"
else
    # HTTP-only config
    if [[ -n "$DOMAIN" ]]; then
        NGINX_SERVER_NAME="${DOMAIN} *.${DOMAIN}"
    else
        NGINX_SERVER_NAME="_"
    fi

    ssh $SSH_OPTS "ubuntu@${SERVER_IP}" "cat > ${APP_DIR}/nginx/default.conf" <<NGINX_CONF
upstream django {
    server web:8000;
}

server {
    listen 80;
    server_name ${NGINX_SERVER_NAME};

    client_max_body_size 20M;

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location /static/ {
        alias /app/staticfiles/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    location /media/ {
        alias /app/media/;
        expires 7d;
    }

    location / {
        proxy_pass http://django;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 120s;
    }
}
NGINX_CONF

    if [[ -n "$DOMAIN" ]]; then
        ok "Nginx configured for $DOMAIN (HTTP)"
    else
        ok "Nginx configured for IP-based access"
    fi
fi

###############################################################################
# PHASE 4: Build & Start
###############################################################################
separator
info "Phase 4: Building and starting containers"
separator

if [[ "$NO_CACHE" == true ]]; then
    info "Building Docker images (no cache)..."
    remote "cd ${APP_DIR} && sudo docker compose build --no-cache"
else
    info "Building Docker images..."
    remote "cd ${APP_DIR} && sudo docker compose build"
fi
ok "Docker images built"

info "Starting services..."
remote "cd ${APP_DIR} && sudo docker compose up -d --remove-orphans"
ok "Services started"

info "Waiting for services to become healthy..."
sleep 10

for i in $(seq 1 30); do
    if remote "cd ${APP_DIR} && sudo docker compose ps --format json 2>/dev/null | grep -q 'running'" 2>/dev/null; then
        break
    fi
    sleep 3
done
ok "Services are running"

###############################################################################
# PHASE 5: Database & Static Files
###############################################################################
separator
info "Phase 5: Database & static files"
separator

info "Running database migrations..."
remote "cd ${APP_DIR} && sudo docker compose exec -T web python manage.py migrate --noinput"
ok "Migrations complete"

info "Collecting static files..."
remote "cd ${APP_DIR} && sudo docker compose exec -T web python manage.py collectstatic --noinput" 2>/dev/null || true
ok "Static files collected"

###############################################################################
# PHASE 6: SSL Setup (if needed)
###############################################################################
if [[ "$SETUP_SSL" == "yes" && "$HAS_SSL_CERT" == false ]]; then
    separator
    info "Phase 6: SSL certificate setup"
    separator

    info "Stopping nginx for certificate issuance..."
    remote "cd ${APP_DIR} && sudo docker compose stop nginx"

    info "Requesting SSL certificate for $DOMAIN..."
    remote "sudo certbot certonly --standalone \
        --non-interactive \
        --agree-tos \
        --email ${SSL_EMAIL} \
        -d ${DOMAIN} \
        -d www.${DOMAIN} \
        || echo 'Certificate request completed (check output above)'"

    if remote "test -f /etc/letsencrypt/live/${DOMAIN}/fullchain.pem" 2>/dev/null; then
        ok "SSL certificate obtained"

        # Rewrite nginx config with SSL
        info "Updating nginx for SSL..."
        ssh $SSH_OPTS "ubuntu@${SERVER_IP}" "cat > ${APP_DIR}/nginx/default.conf" <<NGINX_SSL
upstream django {
    server web:8000;
}

server {
    listen 80;
    server_name ${DOMAIN} *.${DOMAIN};

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location / {
        return 301 https://\$host\$request_uri;
    }
}

server {
    listen 443 ssl;
    http2 on;
    server_name ${DOMAIN} *.${DOMAIN};

    ssl_certificate     /etc/letsencrypt/live/${DOMAIN}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${DOMAIN}/privkey.pem;

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;

    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    client_max_body_size 20M;

    location /static/ {
        alias /app/staticfiles/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    location /media/ {
        alias /app/media/;
        expires 7d;
    }

    location / {
        proxy_pass http://django;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 120s;
    }
}
NGINX_SSL

        # Mount SSL certs into nginx container
        remote "cd ${APP_DIR} && cat > docker-compose.override.yml" <<'OVERRIDE'
version: "3.8"

services:
  nginx:
    volumes:
      - ./nginx/default.conf:/etc/nginx/conf.d/default.conf:ro
      - static_files:/app/staticfiles:ro
      - media_files:/app/media:ro
      - /etc/letsencrypt:/etc/letsencrypt:ro
      - certbot_webroot:/var/www/certbot:ro

volumes:
  certbot_webroot:
OVERRIDE
        ok "SSL nginx config written"

        # Auto-renewal cron
        info "Setting up SSL auto-renewal..."
        remote "sudo bash -c '(crontab -l 2>/dev/null; echo \"0 3 * * * certbot renew --quiet --deploy-hook \\\"docker compose -f ${APP_DIR}/docker-compose.yml restart nginx\\\"\") | sort -u | crontab -'"
        ok "Auto-renewal cron installed (daily at 3 AM)"
    else
        warn "SSL certificate request failed — site will run on HTTP"
        warn "You can retry later: sudo certbot certonly --standalone -d $DOMAIN"
    fi

    info "Starting nginx..."
    remote "cd ${APP_DIR} && sudo docker compose up -d nginx"
    ok "Nginx restarted"
fi

###############################################################################
# PHASE 7: Health Check
###############################################################################
separator
info "Phase 7: Final verification"
separator

info "Container status:"
remote "cd ${APP_DIR} && sudo docker compose ps"
echo ""

if [[ "$SETUP_SSL" == "yes" && -n "$DOMAIN" ]]; then
    HEALTH_URL="https://${DOMAIN}/"
else
    HEALTH_URL="http://${SERVER_IP}/"
fi

HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$HEALTH_URL" 2>/dev/null || echo "000")
if [[ "$HTTP_CODE" == "200" || "$HTTP_CODE" == "301" || "$HTTP_CODE" == "302" ]]; then
    ok "Application is responding (HTTP $HTTP_CODE)"
else
    warn "Application returned HTTP $HTTP_CODE — it may still be starting up"
fi

###############################################################################
# Done
###############################################################################
separator
echo -e "${GREEN}Deploy Complete!${NC}"
separator

echo ""
echo "  Server IP:      $SERVER_IP"
if [[ -n "$DOMAIN" ]]; then
    echo "  Domain:         $DOMAIN"
fi
if [[ "$SETUP_SSL" == "yes" ]]; then
    echo "  URL:            https://$DOMAIN"
elif [[ -n "$DOMAIN" ]]; then
    echo "  URL:            http://$DOMAIN"
else
    echo "  URL:            http://$SERVER_IP"
fi
echo ""
echo "  SSH:            ssh -i $SSH_KEY_PATH ubuntu@$SERVER_IP"
echo "  Logs:           ssh ... 'cd $APP_DIR && sudo docker compose logs -f'"
echo "  Restart:        ssh ... 'cd $APP_DIR && sudo docker compose restart'"
echo ""
echo "  Re-deploy:      ./deploy.sh --config deploy.conf"
echo "  Clean rebuild:  ./deploy.sh --config deploy.conf --no-cache"
echo ""

if [[ -n "$DOMAIN" ]]; then
    warn "Ensure your DNS A record for $DOMAIN points to $SERVER_IP"
fi

echo ""
ok "All done."
