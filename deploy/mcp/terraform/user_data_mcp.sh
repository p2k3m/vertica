#!/bin/bash
set -euxo pipefail

dnf update -y
dnf install -y docker jq awscli curl
systemctl enable --now docker

REGION="${aws_region}"
ACCOUNT_ID="${aws_account_id}"
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"

IMAGE="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${mcp_image_repo}:latest"
docker pull "$IMAGE"

cat >/opt/mcp.env <<EOF_INNER
DB_HOST=${db_host}
DB_PORT=5433
DB_USER=dbadmin
DB_PASSWORD=
DB_NAME=VMart
MCP_HTTP_TOKEN=${mcp_http_token}
EOF_INNER

docker run -d --name mcp_vertica --restart unless-stopped \
  --env-file /opt/mcp.env \
  -p 8000:8000 \
  "$IMAGE"

cat >/usr/local/bin/mcp-smoke.sh <<'SMOKE'
#!/usr/bin/env bash
set -e
curl -fsSL http://127.0.0.1:8000/healthz
SMOKE
chmod +x /usr/local/bin/mcp-smoke.sh
