### A. Preflight & Secrets (10)

1. Write a bash function `require_env VAR` that fails with ❌ if `$VAR` is empty and prints a clear message.
2. Create a composite action `.github/actions/check-secrets` that validates a list of env names.
3. Add a job `preflight` that checks: AWS_REGION, AWS_ACCOUNT_ID, ALLOWED_CIDRS, VERTICA_* and MCP_HTTP_TOKEN.
4. Emit a markdown summary listing which secrets were found vs missing (do not print values).
5. Fail the workflow if `ALLOWED_CIDRS` includes `0.0.0.0/0`.
6. Add JSON schema for required secrets and a jq-based validator step.
7. Detect if `AWS_ROLE_TO_ASSUME` is set; if so, skip key usage; else require keys.
8. Create reusable `check-aws-auth` step that calls STS and prints caller ARN.
9. Guard that `VERTICA_IMAGE_URI` is in the same region as `AWS_REGION`.
10. Add a step that redacts secrets from `::debug::` logs.

### B. Terraform State & Backend (10)

1. Write `infra/backend-bootstrap.sh` to create S3 bucket (versioned) and DynamoDB lock table.
2. Teach the script to be idempotent and export `TF_BACKEND_BUCKET/TABLE` to `$GITHUB_ENV`.
3. Add `backend.tf` referencing `var.tf_backend_bucket` and `var.tf_backend_ddb_table`.
4. Pin Terraform 1.9.x in CI, download if missing, and run `init -upgrade`.
5. Generate a minimal `README` section explaining how state is protected against concurrent ops.
6. Add a `terraform fmt -check` step in CI.
7. Add `tflint` config and lint step with common AWS rules.
8. Generate a pre-commit config to run fmt, validate, tflint locally.
9. Add a CI artifact that stores `terraform plan` output on PRs.
10. Add graceful `destroy` job gated behind `workflow_dispatch` + confirmation input.

### C. IAM & Least Privilege (10)

1. Author an instance role with only: SSMCore, CWAgent, ECRReadOnly.
2. Generate a custom policy that restricts ECR actions to two repos: `mcp-vertica` and `vertica-ce`.
3. Add a repo policy example for **cross-account** ECR pull of `vertica-ce`.
4. Block instance metadata v1 by requiring IMDSv2 only.
5. Emit a policy that denies `ec2:AssociateIamInstanceProfile` except for our profile.
6. Add SCP text (comment) that denies `ecr:DeleteRepository` unless tag `Keep=true`.
7. Generate a CloudTrail filter to watch for `GetAuthorizationToken` failures.
8. Add a KMS CMK (optional) to encrypt EBS and S3 state; wire up.
9. Create a CI step to run `iam-policy-validator` (open-source) on inline policies.
10. Add doc notes on rotating `MCP_HTTP_TOKEN` safely.

### D. Networking & Security Groups (10)

1. Create a security group that only allows 8000/5433 from `allowed_cidrs`.
2. Add an egress allow-list variant: 53/udp, 80/tcp, 443/tcp only.
3. Generate a tf variable validation that `allowed_cidrs` are valid CIDRs.
4. Add VPC flow logs to S3 (optional) and lifecycle policy to expire after 7 days.
5. Provide iptables script to block lateral movement inside the instance.
6. Add `fail2ban` config to drop abusive IPs on port 8000.
7. Create CloudWatch metric filter for rejected SG connections.
8. Add SSM document that toggles maintenance mode (blocks 8000 with iptables).
9. Add a test that ports are closed to any non-allowed CIDR using `nmap` in CI (skipped by default).
10. Document how to quickly add your home IP: `curl ifconfig.me` → update secret → rerun.

### E. EC2 Sizing & Cost Controls (10)

1. Parameterize `instance_type` with default `t3.xlarge`; warn if set below 8GB RAM.
2. Add `ttl_hours` that schedules `shutdown -h` via `at`.
3. Emit a `cost.md` explaining Spot interruptions and how to reprovision.
4. Add tag `AutoTTL=<hours>` to the instance; write TTL into `/etc/motd`.
5. Provide `terraform apply -target` commands to update SG without instance replace.
6. Add SSM automation to stop/start instance from CI.
7. Add a step to prune old Docker images on boot (`docker system prune -f`).
8. Parameterize `volume_size_gb` (default 50) and show how to grow filesystem.
9. Add a CloudWatch alarm on CPUCreditBalance < 20 (T family).
10. Generate a weekly reminder comment in the repo if instance is running.

### F. Docker & Compose (10)

1. Compose service `vertica` with `healthcheck` using `nc -z 127.0.0.1 5433`.
2. Compose service `mcp` depends_on `vertica:service_healthy`.
3. Mount `/var/lib/vertica` volume for data persistence.
4. Emit a `compose.override.yml` for local dev with bind-mounted source.
5. Add `no-new-privileges: true` and `read_only: true` for `mcp` (where possible).
6. Use `log-driver: json-file` with `max-size: 10m` and `max-file: 3`.
7. Add `restart: unless-stopped` and discuss tradeoffs.
8. Provide a `docker login` helper that retries on throttling.
9. Add a tiny `wait-for-port.py` and wire it into scripts.
10. Document how to shell into the container for debugging without SSH.

### G. MCP Server Code (10)

1. Add FastAPI `/healthz` that returns `{ok:true}` and sql_dir path.
2. Implement token auth via `Authorization: Bearer <token>` header.
3. Create `SAFE_NAME` regex to prevent path traversal in template names.
4. Add `tenacity` retry on Vertica connect with backoff.
5. Wrap queries with `SELECT * FROM (…) LIMIT :n` to guard row counts.
6. Add `GET /api/info` returning DB version via a lightweight query.
7. Return `columns`, `rows`, `row_count`, and the `sql` actually run.
8. Log structured JSON to stdout with timing and row_count.
9. Add `X-Request-Id` support in request/response headers.
10. Provide sample tool definition for a future MCP stdio client.

### H. SQL Templates (10)

1. Add `sql/get_version.sql` for baseline checks.
2. Create `sql/list_schemas.sql` with optional `LIKE :pattern` param.
3. Make a `sql/top_tables.sql` ordered by row_count (if metadata available).
4. Create a template that shows events in the last N hours.
5. Add a query that validates presence of a known table and returns 0/1.
6. Provide a query that samples N rows from a table (randomized).
7. Emit a template that enforces `WHERE` when accessing wide tables.
8. Add a `sql/diagnostics.sql` collecting session settings.
9. Provide a `sql/permissions.sql` listing roles & grants for a user.
10. Template that checks for lock waits and returns offenders.

### I. Testing (pytest) (10)

1. Unit test `/healthz` status and shape.
2. Test template name guard against `../../`.
3. Test render of `get_version.sql` includes `SELECT`.
4. Mock `vertica_python.connect` and verify retries on failure.
5. Integration test (skipped) that calls `/api/query` if `VERTICA_*` envs are set.
6. Contract test that `row_count` ≤ limit passed.
7. Performance micro-benchmark for render + query pipeline (skipped in CI).
8. Snapshot test for JSON schema of `/api/query` response.
9. Lint test ensuring no `format(sql)` concatenations exist (safety).
10. Test that bearer token is required when `MCP_HTTP_TOKEN` is non-empty.

### J. CI/CD Flow (10)

1. Build MCP image from `Dockerfile.mcp` and push to ECR with `latest` + SHA tags.
2. Create `Ensure MCP ECR repo exists` idempotent step.
3. Terraform apply with variables wired from secrets.
4. Use SSM `send-command` to run smoke checks (`curl /healthz`, query endpoint).
5. Publish `MCP URL` and `Vertica address` in `GITHUB_STEP_SUMMARY`.
6. Add a manual `destroy` input; on destroy, run `terraform destroy` and confirm.
7. Upload container logs as an artifact if smoke test fails.
8. Gate deploy to `main` only; allow PR plan-only runs.
9. Add concurrency group so only one deploy runs at a time.
10. Use OIDC first; fallback to static keys.

### K. Observability & Logs (10)

1. Install CloudWatch Agent via SSM to ship Docker logs.
2. Create a log group `vertica-mcp` with 7-day retention.
3. Add metric filter for `HTTPException` count.
4. Emit an alarm for `/api/query` 5xx > 2 in 5 minutes.
5. Add a `/metrics` endpoint (optional) with process stats.
6. Write a Loki/Grafana section (optional) for self-hosted.
7. Add request timing middleware and log p95.
8. Tag CloudWatch logs with instanceId for correlation.
9. Add a `diag` tool that prints container versions.
10. Write `observability.md` explaining where to look when things break.

### L. Security & Hardening (10)

1. Document token rotation procedure for `MCP_HTTP_TOKEN`.
2. Add `read_only` FS for mcp container and a writable `/tmp`.
3. Run mcp container as non-root UID/GID.
4. Disable service banners; suppress stack traces in 4xx.
5. Add rate limiting via proxy (optional).
6. Enforce TLS (ALB + ACM) if you enable public production use.
7. Provide `curl` examples with `-H 'Authorization: Bearer …'`.
8. Add CSP headers if serving any static content (not needed here).
9. Write a `SECURITY.md` with contact/process.
10. Add a CI step that checks container base image CVEs (trivy/grype).
