#!/bin/bash
set -euxo pipefail

REGION="${region}"
ACCOUNT_ID="${account_id}"
VERTICA_IMAGE_URI="${vertica_image_uri}"
MCP_REPO_URI="${mcp_repo_uri}"
V_USER="${vertica_user}"
V_PASS="${vertica_password}"
V_DB="${vertica_database}"
MCP_TOKEN="${mcp_http_token}"
TTL_HOURS="${ttl_hours}"

amazon-linux-extras enable docker || true
yum install -y docker jq curl unzip nc at
systemctl enable --now docker
systemctl enable --now atd || true
usermod -aG docker ec2-user || true

mkdir -p /usr/local/lib/docker/cli-plugins
curl -SL "https://github.com/docker/compose/releases/download/v2.29.7/docker-compose-linux-x86_64" -o /usr/local/lib/docker/cli-plugins/docker-compose
chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com"
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "${VERTICA_IMAGE_URI%%/*}"

docker system prune -f || true

mkdir -p /opt/stack
cat > /opt/stack/compose.remote.yml <<'YAML'
services:
  vertica:
    image: ${VERTICA_IMAGE_URI}
    container_name: vertica
    restart: unless-stopped
    ports: ["5433:5433"]
    volumes:
      - /var/lib/vertica:/data
    healthcheck:
      test: ["CMD-SHELL", "nc -z 127.0.0.1 5433 || exit 1"]
      interval: 10s
      timeout: 3s
      retries: 30
  mcp:
    image: ${MCP_REPO_URI}:latest
    container_name: mcp
    restart: unless-stopped
    environment:
      VERTICA_HOST: vertica
      VERTICA_PORT: "5433"
      VERTICA_USER: ${V_USER}
      VERTICA_PASSWORD: ${V_PASS}
      VERTICA_DATABASE: ${V_DB}
      MCP_HTTP_TOKEN: ${MCP_TOKEN}
    depends_on:
      vertica:
        condition: service_healthy
    ports: ["8000:8000"]
    healthcheck:
      test: ["CMD", "curl", "-sf", "http://127.0.0.1:8000/healthz"]
      interval: 10s
      timeout: 3s
      retries: 30
YAML

cd /opt/stack
/usr/local/lib/docker/cli-plugins/docker-compose -f compose.remote.yml up -d

if [ "$TTL_HOURS" -gt 0 ]; then
  at now + ${TTL_HOURS} hours <<<'shutdown -h now' || true
fi

PUB_IP=$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4 || true)
cat >/etc/motd <<'MOTD'
Vertica MCP ready.
- MCP:     http://$PUB_IP:8000 (Bearer ${MCP_TOKEN})
- Vertica: $PUB_IP:5433  (db=${V_DB}, user=${V_USER})
MOTD
