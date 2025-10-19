#!/usr/bin/env bash
set -Eeuo pipefail
exec > >(tee /var/log/user-data.log|logger -t user-data -s 2>/dev/console) 2>&1

REGION="ap-south-1"
VERTICA_IMAGE_URI="${VERTICA_IMAGE_URI}"
MCP_IMAGE_URI="${AWS_ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${MCP_IMAGE_REPO}:${MCP_IMAGE_TAG}"
MCP_HTTP_TOKEN="${MCP_HTTP_TOKEN}"

# 1) Install basics
dnf update -y
amazon-linux-extras enable docker
dnf install -y docker jq
systemctl enable --now docker

# 2) ECR login(s)
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin ${AWS_ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com || true
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin 957650740525.dkr.ecr.${REGION}.amazonaws.com || true

# 3) Mount data volume
mkfs -t ext4 /dev/sdh || true
mkdir -p /var/lib/vertica
mount /dev/sdh /var/lib/vertica || true
echo "/dev/sdh /var/lib/vertica ext4 defaults,nofail 0 2" >> /etc/fstab

# 4) Write compose file
cat >/opt/compose.remote.yml <<'YAML'
version: "3.9"
services:
  vertica:
    image: "${VERTICA_IMAGE_URI}"
    container_name: vertica_ce
    ports: ["5433:5433"]
    volumes: ["/var/lib/vertica:/data"]
    ulimits: { nofile: 65536 }
    restart: unless-stopped
  mcp:
    image: "${MCP_IMAGE_URI}"
    container_name: mcp_vertica
    environment:
      VERTICA_HOST: vertica
      VERTICA_PORT: "5433"
      VERTICA_DATABASE: "vmart"
      VERTICA_USER: "dbadmin"
      VERTICA_PASSWORD: "password"
      VERTICA_SSL: "false"
      VERTICA_SSL_REJECT_UNAUTHORIZED: "false"
      VERTICA_CONNECTION_LIMIT: "8"
      VERTICA_SCHEMA: "mf_shared_provider_default"
      VIEW_BS_TO_CI: "v_bs_to_ci_edges"
      MCP_HTTP_TOKEN: "${MCP_HTTP_TOKEN}"
    ports: ["8000:8000"]
    depends_on: [vertica]
    restart: unless-stopped
YAML

# 5) Boot
cd /opt
docker compose -f compose.remote.yml up -d

# 6) Health wait
for i in {1..60}; do
  if curl -sf http://127.0.0.1:8000/healthz >/dev/null; then echo ready; exit 0; fi
  sleep 5
done
exit 1
