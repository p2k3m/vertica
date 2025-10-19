#!/usr/bin/env bash
set -euo pipefail
: "${AWS_REGION:?Missing AWS_REGION}"
: "${AWS_ACCOUNT_ID:?Missing AWS_ACCOUNT_ID}"

BUCKET="vertica-mcp-tf-${AWS_ACCOUNT_ID}-${AWS_REGION}"
TABLE="vertica-mcp-tf-locks"

if ! aws s3api head-bucket --bucket "$BUCKET" >/dev/null 2>&1; then
  aws s3api create-bucket \
    --bucket "$BUCKET" \
    --create-bucket-configuration LocationConstraint="$AWS_REGION"
fi

if ! aws dynamodb describe-table --table-name "$TABLE" >/dev/null 2>&1; then
  aws dynamodb create-table \
    --table-name "$TABLE" \
    --attribute-definitions AttributeName=LockID,AttributeType=S \
    --key-schema AttributeName=LockID,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST
fi

echo "Backend ready: s3://$BUCKET  ddb:$TABLE"
