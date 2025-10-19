#!/usr/bin/env bash
set -euo pipefail
INST_ID=$1
MCP_TOKEN=$2

aws ssm send-command \
  --document-name "AWS-RunShellScript" \
  --instance-ids "$INST_ID" \
  --parameters commands='[
    "set -e",
    "curl -sf http://127.0.0.1:8000/healthz",
    "curl -sf -H \"Authorization: Bearer '$MCP_TOKEN'\" -H \"Content-Type: application/json\" -d \\
       '{\\"template\\":\\"get_version.sql\\",\\"params\\":{}}' http://127.0.0.1:8000/api/query"
  ]' \
  --query 'Command.CommandId' --output text
