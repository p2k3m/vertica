# Vertica MCP Platform

This repository packages a production-style Model Context Protocol (MCP) server that connects
Claude to Vertica CE locally and in AWS. It includes:

* A hardened MCP server with configurable auth, health checks, and SQL templates stored under `sql/`.
* Docker tooling for local development and a purpose-built `Dockerfile.mcp` image.
* Terraform IaC that provisions a single EC2 instance with Vertica CE + the MCP server running via Docker Compose.
* A GitHub Actions pipeline that builds the MCP image, pushes it to ECR, provisions infrastructure, and
  smoke-tests via AWS Systems Manager.
* Documentation for connecting Claude Desktop on macOS and Windows (local stdio or remote HTTP via Smithery).
* Cost and security guardrails that default to Spot instances and IP-restricted security groups.

## Repository map

```
.
├─ infra/                # Terraform + user data for the EC2 stack
├─ sql/                  # Parameterised SQL templates consumed by the MCP tools
├─ src/mcp_vertica/      # MCP server implementation
├─ tests/                # Unit tests and SQL contract checks
├─ .github/workflows/    # CI/CD pipeline
├─ Dockerfile.mcp        # Container image for the MCP server
├─ docker-compose.yml    # Local Vertica CE + MCP developer stack
├─ Makefile              # Convenience targets (install, lint, test, local-up)
└─ PROMPTS.md            # Automation prompts for your codex agent
```

## Local development quickstart

1. **Install prerequisites**

   * Docker Desktop
   * Python 3.12+
   * [`uv`](https://github.com/astral-sh/uv) (recommended for dependency management)

2. **Sync dependencies and run tests**

   ```bash
   uv sync --frozen
   uv run pytest -q
   uv run ruff check
   ```

3. **Bring up Vertica CE + the MCP server locally**

   ```bash
   docker compose up --build -d
   ./scripts/wait-for-port.py localhost 8000 --timeout 120
   curl http://127.0.0.1:8000/healthz
   ```

   The MCP container exposes port `8000` for HTTP transport and publishes the SSE transport via `uvicorn`.

4. **Launch Claude Desktop (local/stdio)**

   *Open `Settings → Developers → Add MCP server`* and add:

   ```json
   {
     "name": "vertica-local",
     "command": ["uvx", "mcp-vertica", "--transport", "stdio"],
     "workingDirectory": "."
   }
   ```

   Claude Desktop will launch the server over stdio and automatically expose all registered tools.

5. **Smoke test tools**

   ```bash
   uv run python -m mcp_vertica --transport http --port 8000
   curl -H 'Accept: application/json' http://127.0.0.1:8000/api/info
   ```

## AWS deployment (Terraform)

The `infra/` module provisions an Amazon Linux 2023 EC2 instance (default `t3.xlarge`, Spot by default) with:

* IAM role + instance profile scoped for SSM, CloudWatch, and read-only ECR access
* Security group allowing Vertica (5433) and MCP HTTP (8000) only from `var.allowed_cidrs`
* gp3 EBS volume mounted at `/var/lib/vertica`
* User data that installs Docker, logs into ECR, writes `compose.remote.yml`, and boots Vertica + MCP containers
* Optional MCP HTTP token enforcement (`var.mcp_http_token`)

> **Backend state** — Run `infra/backend-bootstrap.sh` once (AWS credentials required) to create the S3 bucket and DynamoDB
> table referenced in `main.tf`.

Manual workflow:

```bash
cd infra
aws configure sso # or export AWS credentials / assume role
./backend-bootstrap.sh
terraform init -upgrade
terraform apply -auto-approve \
  -var="aws_account_id=<your-account-id>" \
  -var="allowed_cidrs=[\"1.2.3.4/32\"]" \
  -var="mcp_http_token=<random-string>"
```

Outputs expose the instance ID, public IP, and the ECR repository URI. The instance exposes HTTP `:8000` for the MCP server and
Vertica on `:5433`.

To tear down:

```bash
terraform destroy -auto-approve
```

## GitHub Actions pipeline

`.github/workflows/cicd.yml` orchestrates end-to-end provisioning.

* **Triggers** — `push` to `main` (apply) and manual `workflow_dispatch` (apply or destroy)
* **Jobs**
  * `lint-test`: installs dependencies with `uv`, runs Ruff + pytest
  * `build`: builds `Dockerfile.mcp`, tags images with the git SHA and `latest`, pushes to `${AWS_ACCOUNT_ID}.dkr.ecr…`
  * `deploy`: bootstraps remote Terraform state, runs `terraform plan/apply`, waits for SSM, and runs smoke tests via `AWS-RunShellScript`
  * `destroy`: manual workflow path that runs `terraform destroy`
* **Authentication** — Prefer OIDC + `AWS_ROLE_TO_ASSUME`; the workflow falls back to static `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`
  when no role is provided. Missing credentials cause an immediate failure with a descriptive error.
* **Smoke tests** — `curl http://127.0.0.1:8000/healthz`, `docker ps`, and `timeout 5 bash -c 'echo > /dev/tcp/127.0.0.1/5433'` executed via SSM.

Configure these GitHub secrets/variables:

| Name | Type | Notes |
| ---- | ---- | ----- |
| `AWS_ACCOUNT_ID` | Secret | Required for ECR tagging |
| `AWS_ROLE_TO_ASSUME` | Secret | Optional; enables OIDC fast-path |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | Secret | Only used if OIDC role absent |
| `MCP_HTTP_TOKEN` | Secret | Populates `MCP_HTTP_TOKEN` for remote deployments |
| `VERTICA_IMAGE_URI` | Variable | Override Vertica CE image if needed |
| `ALLOWED_CIDRS_JSON` | Variable | JSON array (e.g. `["203.0.113.10/32"]`) |

## Claude Desktop (macOS + Windows)

### Local stdio transport

1. Ensure Vertica + MCP are running locally (Docker compose).
2. In Claude Desktop → *Developers* → *Add MCP server*, add:

   ```json
   {
     "name": "vertica-local",
     "command": ["uvx", "mcp-vertica", "--transport", "stdio"],
     "workingDirectory": "C:/path/to/repo" // adjust for Windows
   }
   ```

3. Restart Claude Desktop. The Vertica tools appear automatically.

### Remote HTTP via Smithery

1. From your laptop (macOS or Windows), ensure your IP is present in `allowed_cidrs` and the MCP HTTP token is set.
2. Deploy via GitHub Actions or Terraform. Confirm health: `curl -H 'X-API-Key: <token>' http://<public-ip>:8000/healthz`.
3. Import `smithery.yaml` in [Smithery](https://smithery.ai) and provide the remote endpoint URL
   (`https://<public-ip>:8000` or behind your own HTTPS proxy).
4. In Claude Desktop, install the Smithery integration profile. Claude forwards MCP traffic over HTTPS to your remote server.

### Troubleshooting Claude connections

* `401 unauthorized` — Ensure `MCP_HTTP_TOKEN` is set (env variable on the instance) and passed via `X-API-Key`.
* `connection refused` — Confirm the security group permits your IP and the instance is running.
* `tool missing` — Check `/tools.json` to verify the MCP server registered your tools; restart the container if necessary.

## Security & operations

* The EC2 security group defaults to `127.0.0.1/32`; set explicit CIDRs before applying.
* Enabling HTTP auth (`MCP_HTTP_TOKEN`) is strongly recommended whenever `allowed_cidrs` covers non-trivial ranges.
* `MCP_READ_ONLY=true` disables inserts/updates/DDL regardless of allowlists.
* Logs: `/var/log/user-data.log`, `/var/log/cloud-init-output.log`, and Docker logs for each container (`docker logs mcp-vertica`).
* Retrieve connection details quickly: `aws ssm start-session --target <instance-id>` for interactive debugging.

## Cost controls

* `use_spot = true` (default) to leverage EC2 Spot pricing; change to `false` for demos needing interruption resilience.
* `ebs_size_gb` defaults to `100`; adjust as needed. `gp3` allows later resizing without downtime.
* Stop the instance when idle to suspend compute charges (`aws ec2 stop-instances`).
* Run `workflow_dispatch → action: destroy` or `terraform destroy` after demos to remove all resources.

## Observability endpoints

* `GET /healthz` — Primary health check for load balancers / SSM
* `GET /_alive` — Lightweight TCP probe for faster boot detection
* `GET /api/info` — Returns version, pool size, and schema allowlists
* `GET /tools.json` — Snapshot of registered tools and descriptions

## Prompts for your automation agent

`PROMPTS.md` contains 110 production-style prompts grouped by category (infra, CI/CD, MCP, security, etc.) that you can feed into
Codex-like agents for incremental automation.

## Troubleshooting

| Symptom | Resolution |
| ------- | ---------- |
| `terraform init` fails with missing bucket | Run `infra/backend-bootstrap.sh` with valid AWS credentials |
| MCP container exits immediately | Check `/var/log/user-data.log` for environment issues, verify ECR image URIs |
| Claude Desktop cannot reach remote server | Verify security group, token, and that Smithery is pointing to the HTTPS endpoint |
| Workflow fails with credential error | Provide `AWS_ROLE_TO_ASSUME` (preferred) or static access keys in repository secrets |

## Upgrades

* Scale vertically by increasing `instance_type` (e.g. `r6i.2xlarge`) in Terraform or GitHub variables.
* Promote to ECS/EKS by reusing the MCP container image and referencing the SQL templates packaged in this repository.
* Extend tools by adding SQL templates under `sql/` and registering new functions in `src/mcp_vertica/mcp.py`.
