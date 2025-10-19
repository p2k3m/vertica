#!/bin/bash
set -euxo pipefail

REGION="${region}"
ACCOUNT_ID="${aws_account_id}"
VERTICA_IMAGE_URI="${vertica_image_uri}"
MCP_IMAGE_URI="${mcp_image_uri}"
MCP_HTTP_TOKEN="${mcp_http_token}"

exec 1>>/var/log/user-data.log 2>&1

dnf update -y

dnf install -y docker docker-compose-plugin jq awscli
systemctl enable docker
systemctl start docker

mkfs -t xfs /dev/xvdf || true
mkdir -p /var/lib/vertica
if ! mount | grep -q '/var/lib/vertica'; then
  mount /dev/xvdf /var/lib/vertica
fi
grep -q '/var/lib/vertica' /etc/fstab || echo '/dev/xvdf /var/lib/vertica xfs defaults,nofail 0 2' >> /etc/fstab

aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com"

mkdir -p /opt/mcp
cat >/opt/mcp/compose.remote.yml <<'YAML'
${compose_yaml}
YAML

cat >/opt/mcp/.env <<'ENV'
VERTICA_IMAGE_URI=${vertica_image_uri}
MCP_IMAGE_URI=${mcp_image_uri}
MCP_HTTP_TOKEN=${mcp_http_token}
ENV

cd /opt/mcp
docker compose --env-file /opt/mcp/.env -f /opt/mcp/compose.remote.yml up -d

for i in {1..40}; do
  if curl -fsS http://127.0.0.1:8000/healthz; then
    break
  fi
  sleep 5
done
