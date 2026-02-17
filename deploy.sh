#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# Cloud-Lines AWS Deployment Script
#
# Deploys the full application stack to a single EC2 instance using Docker
# Compose. Handles infrastructure provisioning, Docker installation, SSL
# certificate setup, database migrations, and application launch.
#
# Prerequisites:
#   - AWS CLI v2 installed and configured (aws configure)
#   - An SSH key pair registered in the target AWS region
#   - A domain pointing to the server (for SSL) or willingness to update DNS after
#   - Bash 4+
#
# Usage:
#   ./deploy.sh                      # Interactive — prompts for all values
#   ./deploy.sh --config deploy.conf  # Load saved answers from file
#
# The script will:
#   1. Create a Security Group (or reuse existing)
#   2. Launch an EC2 instance (or connect to existing)
#   3. Install Docker & Docker Compose on the instance
#   4. Copy project files to the server
#   5. Configure environment variables
#   6. Start the Docker Compose stack
#   7. Run database migrations
#   8. Optionally set up SSL with Let's Encrypt
###############################################################################

# ── Colours & helpers ────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No colour

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

# ── Pre-flight checks ───────────────────────────────────────────────────────
command -v aws   >/dev/null 2>&1 || die "AWS CLI is not installed. Install it: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html"
command -v ssh   >/dev/null 2>&1 || die "ssh is not installed."

# rsync is preferred but not required — we fall back to tar+scp
USE_RSYNC=true
if ! command -v rsync >/dev/null 2>&1; then
    USE_RSYNC=false
    warn "rsync not found — falling back to tar + scp (works in AWS CloudShell)"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Load config file if provided ─────────────────────────────────────────────
CONFIG_FILE=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --config) CONFIG_FILE="$2"; shift 2 ;;
        *) die "Unknown argument: $1" ;;
    esac
done

USING_CONFIG=false
if [[ -n "$CONFIG_FILE" && -f "$CONFIG_FILE" ]]; then
    info "Loading configuration from $CONFIG_FILE"
    source "$CONFIG_FILE"
    USING_CONFIG=true
fi

# ── Prompt helpers ───────────────────────────────────────────────────────────
# When a config file is loaded, prompts are skipped entirely — even for empty
# values. This means you can fill in deploy.conf on one screen and run the
# deploy without any interactive input.
prompt() {
    local var_name="$1"
    local prompt_text="$2"
    local default="${3:-}"

    # Skip if variable already has a value
    if [[ -n "${!var_name:-}" ]]; then
        return
    fi

    # Skip if config file is loaded (accept empty values from config)
    if [[ "$USING_CONFIG" == true ]] && declare -p "$var_name" &>/dev/null; then
        return
    fi

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

    # Skip if variable already has a value
    if [[ -n "${!var_name:-}" ]]; then
        return
    fi

    # Skip if config file is loaded (accept empty values from config)
    if [[ "$USING_CONFIG" == true ]] && declare -p "$var_name" &>/dev/null; then
        return
    fi

    read -srp "$(echo -e "${GREEN}?${NC}") $prompt_text: " input
    echo ""
    eval "$var_name=\"$input\""
}

# ── Gather configuration ────────────────────────────────────────────────────
separator
echo -e "${BLUE}Cloud-Lines AWS Deployment${NC}"
echo "This script will deploy your application to AWS."
separator

info "Step 1: AWS Configuration"
prompt AWS_REGION          "AWS Region"                          "eu-west-2"
prompt AWS_KEY_PAIR_NAME   "SSH Key Pair name (registered in AWS)" ""
prompt SSH_KEY_PATH        "Path to SSH private key"             "$HOME/.ssh/${AWS_KEY_PAIR_NAME}.pem"
prompt INSTANCE_TYPE       "EC2 Instance Type"                   "t3.medium"

separator
info "Step 2: Deployment Target"
prompt DEPLOY_MODE         "Deploy mode — 'new' (create instance) or 'existing' (connect to IP)" "new"

if [[ "$DEPLOY_MODE" == "existing" ]]; then
    prompt SERVER_IP "Server IP address" ""
fi

separator
info "Step 3: Domain & SSL"
prompt DOMAIN              "Primary domain (leave blank to use server IP only)"  ""

if [[ -n "$DOMAIN" ]]; then
    prompt SETUP_SSL       "Set up SSL with Let's Encrypt? (yes/no)" "yes"
    if [[ "$SETUP_SSL" == "yes" ]]; then
        prompt SSL_EMAIL    "Email for Let's Encrypt notifications"   ""
    fi
else
    SETUP_SSL="no"
    info "No domain set — site will be accessible via server IP on HTTP"
fi

separator
info "Step 4: Application Configuration"
prompt SITE_NAME           "Site name (subdomain prefix)"        "app"
prompt_secret SECRET_KEY   "Django SECRET_KEY"
prompt_secret DB_PASSWORD  "Database password"

prompt DB_NAME             "Database name"                       "cloudlines"
prompt DB_USER             "Database user"                       "cloudlines"

separator
info "Step 5: AWS Service Keys"
prompt_secret AWS_ACCESS_KEY_ID     "AWS Access Key ID (for S3/SES)"
prompt_secret AWS_SECRET_ACCESS_KEY "AWS Secret Access Key"
prompt AWS_S3_BUCKET               "S3 bucket for media"          "media.cloud-lines.com"

separator
info "Step 6: Stripe Keys"
prompt_secret STRIPE_SECRET_KEY      "Stripe Secret Key"
prompt_secret STRIPE_PUBLIC_KEY      "Stripe Public Key"
prompt_secret STRIPE_TEST_SECRET_KEY "Stripe Test Secret Key (or press enter to skip)"
prompt_secret STRIPE_TEST_PUBLIC_KEY "Stripe Test Public Key (or press enter to skip)"

# ── Validate SSH key ────────────────────────────────────────────────────────
[[ -f "$SSH_KEY_PATH" ]] || die "SSH key not found at $SSH_KEY_PATH"
chmod 600 "$SSH_KEY_PATH" 2>/dev/null || true

SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=10 -i $SSH_KEY_PATH"

# ── Helper: run command on remote server ─────────────────────────────────────
remote() {
    ssh $SSH_OPTS "ubuntu@${SERVER_IP}" "$@"
}

remote_sudo() {
    ssh $SSH_OPTS "ubuntu@${SERVER_IP}" "sudo bash -c '$*'"
}

# ── Save config for future runs ──────────────────────────────────────────────
save_config() {
    local conf="$SCRIPT_DIR/deploy.conf"
    cat > "$conf" <<CONF
# Cloud-Lines Deployment Configuration
# Generated on $(date -u +"%Y-%m-%d %H:%M:%S UTC")
# Re-use with: ./deploy.sh --config deploy.conf

AWS_REGION="$AWS_REGION"
AWS_KEY_PAIR_NAME="$AWS_KEY_PAIR_NAME"
SSH_KEY_PATH="$SSH_KEY_PATH"
INSTANCE_TYPE="$INSTANCE_TYPE"
DEPLOY_MODE="existing"
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
    ok "Configuration saved to deploy.conf (secrets commented out)"
}

###############################################################################
# PHASE 1: Infrastructure
###############################################################################
separator
info "Phase 1: Infrastructure Provisioning"
separator

if [[ "$DEPLOY_MODE" == "new" ]]; then
    # ── Security Group ───────────────────────────────────────────────────────
    SG_NAME="cloudlines-sg"
    info "Creating security group: $SG_NAME"

    # Get default VPC
    VPC_ID=$(aws ec2 describe-vpcs \
        --region "$AWS_REGION" \
        --filters "Name=isDefault,Values=true" \
        --query "Vpcs[0].VpcId" \
        --output text 2>/dev/null || echo "")

    if [[ -z "$VPC_ID" || "$VPC_ID" == "None" ]]; then
        die "No default VPC found in $AWS_REGION. Create one or specify a VPC."
    fi

    # Check if SG already exists
    SG_ID=$(aws ec2 describe-security-groups \
        --region "$AWS_REGION" \
        --filters "Name=group-name,Values=$SG_NAME" "Name=vpc-id,Values=$VPC_ID" \
        --query "SecurityGroups[0].GroupId" \
        --output text 2>/dev/null || echo "")

    if [[ -z "$SG_ID" || "$SG_ID" == "None" ]]; then
        SG_ID=$(aws ec2 create-security-group \
            --region "$AWS_REGION" \
            --group-name "$SG_NAME" \
            --description "Cloud-Lines application server" \
            --vpc-id "$VPC_ID" \
            --query "GroupId" \
            --output text)

        # Allow SSH, HTTP, HTTPS
        aws ec2 authorize-security-group-ingress --region "$AWS_REGION" --group-id "$SG_ID" \
            --ip-permissions \
            "IpProtocol=tcp,FromPort=22,ToPort=22,IpRanges=[{CidrIp=0.0.0.0/0,Description=SSH}]" \
            "IpProtocol=tcp,FromPort=80,ToPort=80,IpRanges=[{CidrIp=0.0.0.0/0,Description=HTTP}]" \
            "IpProtocol=tcp,FromPort=443,ToPort=443,IpRanges=[{CidrIp=0.0.0.0/0,Description=HTTPS}]" \
            >/dev/null

        ok "Security group created: $SG_ID"
    else
        ok "Security group already exists: $SG_ID"
    fi

    # ── EC2 Instance ─────────────────────────────────────────────────────────
    info "Launching EC2 instance ($INSTANCE_TYPE)..."

    # Get latest Ubuntu 22.04 LTS AMI
    AMI_ID=$(aws ec2 describe-images \
        --region "$AWS_REGION" \
        --owners 099720109477 \
        --filters \
            "Name=name,Values=ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*" \
            "Name=state,Values=available" \
        --query "sort_by(Images, &CreationDate)[-1].ImageId" \
        --output text)

    INSTANCE_ID=$(aws ec2 run-instances \
        --region "$AWS_REGION" \
        --image-id "$AMI_ID" \
        --instance-type "$INSTANCE_TYPE" \
        --key-name "$AWS_KEY_PAIR_NAME" \
        --security-group-ids "$SG_ID" \
        --block-device-mappings "DeviceName=/dev/sda1,Ebs={VolumeSize=30,VolumeType=gp3}" \
        --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=cloudlines-${SITE_NAME}}]" \
        --query "Instances[0].InstanceId" \
        --output text)

    ok "Instance launched: $INSTANCE_ID"
    info "Waiting for instance to be running..."

    aws ec2 wait instance-running \
        --region "$AWS_REGION" \
        --instance-ids "$INSTANCE_ID"

    SERVER_IP=$(aws ec2 describe-instances \
        --region "$AWS_REGION" \
        --instance-ids "$INSTANCE_ID" \
        --query "Reservations[0].Instances[0].PublicIpAddress" \
        --output text)

    ok "Instance running at: $SERVER_IP"

    # ── Allocate Elastic IP ──────────────────────────────────────────────────
    info "Allocating Elastic IP..."
    ALLOC_ID=$(aws ec2 allocate-address \
        --region "$AWS_REGION" \
        --domain vpc \
        --query "AllocationId" \
        --output text)

    aws ec2 associate-address \
        --region "$AWS_REGION" \
        --instance-id "$INSTANCE_ID" \
        --allocation-id "$ALLOC_ID" \
        >/dev/null

    SERVER_IP=$(aws ec2 describe-addresses \
        --region "$AWS_REGION" \
        --allocation-ids "$ALLOC_ID" \
        --query "Addresses[0].PublicIp" \
        --output text)

    ok "Elastic IP assigned: $SERVER_IP"
    if [[ -n "$DOMAIN" ]]; then
        warn "Point your DNS A record for $DOMAIN and *.$DOMAIN to $SERVER_IP"
    fi

    # Wait for SSH to become available
    info "Waiting for SSH to become available..."
    for i in $(seq 1 30); do
        if ssh $SSH_OPTS -o BatchMode=yes "ubuntu@${SERVER_IP}" "echo ready" >/dev/null 2>&1; then
            break
        fi
        sleep 5
    done
    ok "SSH connection established"
else
    info "Using existing server at $SERVER_IP"
    # Verify SSH connectivity
    ssh $SSH_OPTS -o BatchMode=yes "ubuntu@${SERVER_IP}" "echo ready" >/dev/null 2>&1 \
        || die "Cannot SSH into $SERVER_IP. Check your key and security group."
    ok "SSH connection verified"
fi

# Save config now that we have the server IP
save_config

###############################################################################
# PHASE 2: Server Setup
###############################################################################
separator
info "Phase 2: Server Setup"
separator

info "Installing Docker and dependencies..."
remote "sudo apt-get update -qq && sudo DEBIAN_FRONTEND=noninteractive apt-get upgrade -y -qq"

# Install Docker
remote 'command -v docker >/dev/null 2>&1 || {
    sudo apt-get install -y -qq ca-certificates curl gnupg
    sudo install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg 2>/dev/null
    sudo chmod a+r /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    sudo apt-get update -qq
    sudo apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    sudo usermod -aG docker ubuntu
}'
ok "Docker installed"

# Set up swap on small instances (≤2 GB RAM) to prevent OOM kills
info "Checking memory and setting up swap if needed..."
remote 'TOTAL_MEM_KB=$(grep MemTotal /proc/meminfo | awk "{print \$2}")
if [ "$TOTAL_MEM_KB" -le 2097152 ] && [ ! -f /swapfile ]; then
    echo "Low memory detected (${TOTAL_MEM_KB}KB) — creating 2GB swap..."
    sudo fallocate -l 2G /swapfile
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile
    sudo swapon /swapfile
    echo "/swapfile none swap sw 0 0" | sudo tee -a /etc/fstab
    echo "Swap enabled."
else
    echo "Swap already exists or memory is sufficient."
fi'
ok "Memory check complete"

###############################################################################
# PHASE 3: Deploy Application
###############################################################################
separator
info "Phase 3: Deploying Application"
separator

APP_DIR="/home/ubuntu/cloud-lines"

info "Syncing project files to server..."
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
    # Fallback: create a tarball excluding unwanted files, upload, and extract
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

# ── Create .env on the server ────────────────────────────────────────────────
info "Creating .env file on server..."

# Build ALLOWED_HOSTS based on whether a domain is configured
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
ok ".env file created"

# ── Update nginx config with actual domain ───────────────────────────────────
info "Configuring nginx..."
ssh $SSH_OPTS "ubuntu@${SERVER_IP}" "mkdir -p ${APP_DIR}/nginx/ssl"

# Use domain-based server_name or catch-all "_" for IP-only access
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

    # Let's Encrypt challenge
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
    ok "Nginx configured for $DOMAIN"
else
    ok "Nginx configured for IP-based access"
fi

# ── Build & Launch ───────────────────────────────────────────────────────────
info "Building and starting Docker containers..."
remote "cd ${APP_DIR} && sudo docker compose build --no-cache"
ok "Docker images built"

info "Starting services..."
remote "cd ${APP_DIR} && sudo docker compose up -d"
ok "All services started"

# Wait for services to be healthy
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
# PHASE 4: Database & Static Files
###############################################################################
separator
info "Phase 4: Database Setup"
separator

info "Running database migrations..."
remote "cd ${APP_DIR} && sudo docker compose exec -T web python manage.py migrate --noinput"
ok "Migrations complete"

info "Collecting static files..."
remote "cd ${APP_DIR} && sudo docker compose exec -T web python manage.py collectstatic --noinput" 2>/dev/null || true
ok "Static files collected"

###############################################################################
# PHASE 5: SSL Setup (Optional)
###############################################################################
if [[ "$SETUP_SSL" == "yes" ]]; then
    separator
    info "Phase 5: SSL Certificate Setup"
    separator

    info "Installing Certbot on server..."
    remote "sudo apt-get install -y -qq certbot"

    info "Stopping nginx temporarily for certificate issuance..."
    remote "cd ${APP_DIR} && sudo docker compose stop nginx"

    info "Requesting SSL certificate for $DOMAIN and *.$DOMAIN..."
    # Use standalone mode for initial certificate
    remote "sudo certbot certonly --standalone \
        --non-interactive \
        --agree-tos \
        --email ${SSL_EMAIL} \
        -d ${DOMAIN} \
        -d www.${DOMAIN} \
        || echo 'SSL certificate request completed (check output above for errors)'"

    # Check if certificate was obtained
    if remote "test -f /etc/letsencrypt/live/${DOMAIN}/fullchain.pem" 2>/dev/null; then
        ok "SSL certificate obtained"

        # Write SSL-enabled nginx config
        info "Configuring nginx for SSL..."
        ssh $SSH_OPTS "ubuntu@${SERVER_IP}" "cat > ${APP_DIR}/nginx/default.conf" <<NGINX_SSL
upstream django {
    server web:8000;
}

# Redirect HTTP to HTTPS
server {
    listen 80;
    server_name ${DOMAIN} *.${DOMAIN};

    # Let's Encrypt challenge
    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location / {
        return 301 https://\$host\$request_uri;
    }
}

# HTTPS server
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

    # HSTS
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

        # Update docker-compose to mount SSL certs and certbot webroot
        info "Updating docker-compose for SSL volume mounts..."
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

        # Set up auto-renewal cron
        info "Setting up SSL auto-renewal..."
        remote "sudo bash -c '(crontab -l 2>/dev/null; echo \"0 3 * * * certbot renew --quiet --deploy-hook \\\"docker compose -f ${APP_DIR}/docker-compose.yml restart nginx\\\"\") | sort -u | crontab -'"
        ok "Auto-renewal cron job installed (daily at 3 AM)"
    else
        warn "SSL certificate request failed. The site will run on HTTP only."
        warn "You can re-run SSL setup later with: sudo certbot certonly --standalone -d $DOMAIN"
    fi

    # Restart nginx with new config
    info "Restarting nginx..."
    remote "cd ${APP_DIR} && sudo docker compose up -d nginx"
    ok "Nginx restarted"
fi

###############################################################################
# PHASE 6: Final Checks
###############################################################################
separator
info "Phase 6: Final Verification"
separator

info "Container status:"
remote "cd ${APP_DIR} && sudo docker compose ps"

echo ""

# Quick health check
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "http://${SERVER_IP}/" 2>/dev/null || echo "000")
if [[ "$HTTP_CODE" == "200" || "$HTTP_CODE" == "301" || "$HTTP_CODE" == "302" ]]; then
    ok "Application is responding (HTTP $HTTP_CODE)"
else
    warn "Application returned HTTP $HTTP_CODE — it may still be starting up"
fi

###############################################################################
# Done
###############################################################################
separator
echo -e "${GREEN}Deployment Complete!${NC}"
separator

echo ""
echo "  Server IP:      $SERVER_IP"
if [[ -n "$DOMAIN" ]]; then
    echo "  Domain:         $DOMAIN"
fi
if [[ "$SETUP_SSL" == "yes" ]]; then
    echo "  URL:            https://$DOMAIN"
else
    if [[ -n "$DOMAIN" ]]; then
        echo "  URL:            http://$DOMAIN"
    else
        echo "  URL:            http://$SERVER_IP"
    fi
fi
echo ""
echo "  SSH Access:     ssh -i $SSH_KEY_PATH ubuntu@$SERVER_IP"
echo "  Logs:           ssh ... 'cd $APP_DIR && sudo docker compose logs -f'"
echo "  Restart:        ssh ... 'cd $APP_DIR && sudo docker compose restart'"
echo "  Re-deploy:      ./deploy.sh --config deploy.conf"
echo ""

if [[ "$DEPLOY_MODE" == "new" && -n "$DOMAIN" ]]; then
    warn "Don't forget to point your DNS A record for $DOMAIN to $SERVER_IP"
fi

echo ""
ok "All done."
