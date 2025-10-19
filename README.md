# Vertica MCP on AWS — One-Click CI/CD (PoC, low-cost)

This repository provisions a spot EC2 instance that runs Vertica CE and an MCP HTTP server beside it. Push to `main` (or trigger `workflow_dispatch`) and the GitHub Actions pipeline will:

1. Build and publish the MCP container image to Amazon ECR.
2. Bootstrap Terraform remote state (S3 + DynamoDB) if needed.
3. Apply Terraform to create IAM, security group, ECR repo, and the EC2 instance.
4. Use AWS Systems Manager to smoke-test `/healthz` and an authenticated SQL query.
5. Publish the MCP + Vertica connection details directly in the workflow summary so you can register the remote MCP with Claude Desktop.

## Repository layout

```
.
├─ .github/workflows/deploy.yml      # One-click pipeline (apply/destroy)
├─ infra/
│  ├─ backend.tf                    # Remote tfstate (S3 + DynamoDB)
│  ├─ backend-bootstrap.sh          # Creates backend bucket/table
│  ├─ main.tf                       # EC2, IAM, SG, ECR repo (MCP)
│  ├─ outputs.tf                    # Public IP, URLs, etc.
│  ├─ userdata.sh                   # Installs Docker; writes compose
│  └─ variables.tf                  # All tunables (low-cost defaults)
├─ src/mcp_vertica/
│  ├─ __init__.py
│  └─ server.py                     # FastAPI + FastMCP + vertica-python
├─ sql/
│  └─ get_version.sql               # Contract check (simple)
├─ tests/
│  ├─ test_health.py                # Unit test of /healthz
│  └─ test_sql_rendering.py         # Template safety/coverage
├─ scripts/
│  ├─ wait-for-port.py              # Local compose bring-up helper
│  └─ ssm_smoke.sh                  # Remote curl/nc via SSM
├─ Dockerfile.mcp                   # Builds MCP image (port 8000)
├─ docker-compose.yml               # Local dev (Mac/Win)
├─ pyproject.toml                   # mcp, fastapi, vertica-python, etc.
└─ PROMPTS.md                       # 120+ Codex prompts grouped
```

## Quick Start

1. **Set repository secrets** (`Settings → Secrets and variables → Actions`). Required:
   * `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` *or* `AWS_ROLE_TO_ASSUME`
   * `AWS_REGION` (default `ap-south-1`)
   * `AWS_ACCOUNT_ID`
   * `ALLOWED_CIDRS` (comma-delimited list like `"49.37.x.x/32","122.166.x.x/32"`)
   * `VERTICA_IMAGE_URI` (`957650740525.dkr.ecr.ap-south-1.amazonaws.com/vertica-ce:v1.0`)
   * `VERTICA_USER`, `VERTICA_PASSWORD`, `VERTICA_DATABASE`
   * `MCP_HTTP_TOKEN` (random bearer token for remote access)
2. **Push to `main`** or run the **`vertica-mcp-cicd`** workflow with `action=apply`.
3. Open the workflow run → **Summary** to grab:
   * MCP URL (`http://<ip>:8000`, use `Bearer <MCP_HTTP_TOKEN>`)
   * Vertica SQL endpoint (`<ip>:5433`, plus DB/user creds)
4. In Claude Desktop → *Settings → Developers → Add MCP server* and register either:
   * **Local (stdio)** – `{ "command": ["uvx","mcp-vertica","--transport","stdio"], "workingDirectory": "." }`
   * **Remote (HTTP)** – URL from the summary, `Authorization: Bearer <MCP_HTTP_TOKEN>`
5. Ask Claude: “Run `get_version.sql` via Vertica MCP” → expect a row with `version()`.

Destroy the stack via `workflow_dispatch` (`action=destroy`) or `terraform destroy -auto-approve` inside `infra/` when finished.

## Local development

```bash
uv sync --frozen
uv run ruff check
uv run pytest -q
VERTICA_IMAGE_URI=957650740525.dkr.ecr.ap-south-1.amazonaws.com/vertica-ce:v1.0 \
VERTICA_USER=dbadmin VERTICA_PASSWORD=example VERTICA_DATABASE=vertica \
MCP_HTTP_TOKEN=local docker compose up --build
./scripts/wait-for-port.py localhost 8000 --timeout 120
curl http://127.0.0.1:8000/healthz
```

## AWS deployment details

* **Instance** – Amazon Linux 2023, default `t3.xlarge`, Spot (override `var.use_spot=false` for stability).
* **Security** – Ports 5433 (Vertica) and 8000 (MCP) are opened only to `var.allowed_cidrs`. IMDSv2 enforced.
* **State** – `infra/backend-bootstrap.sh` provisions a versioned S3 bucket + DynamoDB lock table if names aren’t supplied.
* **User data** – Installs Docker + Compose, logs into ECR, writes `/opt/stack/compose.remote.yml`, starts Vertica and MCP, sets `/etc/motd` with connection hints, and optionally schedules auto-shutdown (`ttl_hours`).
* **Smoke tests** – `scripts/ssm_smoke.sh` runs through AWS Systems Manager (no SSH) to validate `/healthz` and an authenticated `/api/query` using `sql/get_version.sql`.

## MCP API surface

* `GET /healthz` – readiness + SQL directory
* `POST /api/render` – renders a SQL template with parameters (Bearer token required if configured)
* `POST /api/query` – renders and executes the SQL, wrapping with `SELECT * FROM (…) LIMIT :n`

All templates live under `sql/`, guarded by a strict filename regex to prevent traversal. Connections use `vertica-python` with retry (`tenacity`).

## Prompts & automation

`PROMPTS.md` contains 120 categorized prompts covering secrets hygiene, Terraform, IAM, networking, cost controls, Docker, MCP code, SQL templates, testing, CI/CD, observability, and security. Drop them into GitHub Copilot/Codespaces or Claude to scaffold future improvements quickly.

## Troubleshooting

* Check workflow logs for the “Secrets OK” preflight and Terraform outputs.
* Use AWS SSM Session Manager (`aws ssm start-session --target <instance-id>`) for shell access.
* Containers live under Docker Compose on the instance (`docker ps`, `docker logs mcp`, `docker logs vertica`).
* Regenerate connection info by re-running the workflow with `action=apply`.

Happy querying!
