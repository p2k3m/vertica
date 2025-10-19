#!/usr/bin/env bash
set -euo pipefail
REGION=${AWS_REGION:-ap-south-1}
ACC=$(aws sts get-caller-identity --query Account --output text)
BUCKET=${TF_BACKEND_BUCKET:-"tfstate-${ACC}-vertica-mcp"}
TABLE=${TF_BACKEND_DDB_TABLE:-"tf-locks-vertica-mcp"}

aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" \
  --create-bucket-configuration LocationConstraint="$REGION" 2>/dev/null || true
aws s3api put-bucket-versioning --bucket "$BUCKET" --versioning-configuration Status=Enabled
aws dynamodb create-table --table-name "$TABLE" \
  --attribute-definitions AttributeName=LockID,AttributeType=S \
  --key-schema AttributeName=LockID,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST 2>/dev/null || true

echo "TF_BACKEND_BUCKET=$BUCKET" >> $GITHUB_ENV
echo "TF_BACKEND_DDB_TABLE=$TABLE" >> $GITHUB_ENV
