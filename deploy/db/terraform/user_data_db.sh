#!/bin/bash
set -euxo pipefail

dnf update -y
dnf install -y docker unzip jq awscli curl
systemctl enable --now docker

REGION="$(curl -s http://169.254.169.254/latest/meta-data/placement/region)"
ACCOUNT_ID="$(curl -s http://169.254.169.254/latest/dynamic/instance-identity/document | jq -r .accountId)"
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"

VERTICA_IMAGE="${vertica_ecr_image}"
IMAGE_REGISTRY="${VERTICA_IMAGE%%/*}"
if [ "$IMAGE_REGISTRY" != "${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com" ]; then
  aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$IMAGE_REGISTRY"
fi
mkdir -p /var/lib/vertica
docker pull "$VERTICA_IMAGE"
docker run -d --name vertica_ce \
  --restart unless-stopped \
  -p 5433:5433 \
  -v /var/lib/vertica:/data \
  "$VERTICA_IMAGE"

cat >/usr/local/bin/db-smoke.sh <<'SMOKE'
#!/usr/bin/env bash
set -e
docker exec vertica_ce vsql -U dbadmin -d VMart -c "SELECT NOW();"
SMOKE
chmod +x /usr/local/bin/db-smoke.sh
