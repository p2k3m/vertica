#!/usr/bin/env bash
set -euo pipefail
REGION=${1:-ap-south-1}
BUCKET=${2:-tf-state-vertica-mcp-$RANDOM}
TABLE=${3:-tf-lock-vertica-mcp}
aws s3 mb s3://$BUCKET --region $REGION
aws dynamodb create-table --table-name $TABLE \
  --attribute-definitions AttributeName=LockID,AttributeType=S \
  --key-schema AttributeName=LockID,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST --region $REGION
cat <<EOF
backend "s3" {
  bucket = "$BUCKET"
  key    = "infra/terraform.tfstate"
  region = "$REGION"
  dynamodb_table = "$TABLE"
}
EOF
