# Vertica MCP on AWS — Two-stack CI/CD

This repository provisions two isolated stacks on AWS:

* **DB stack** (`deploy/db/**`) — Spot `t3.xlarge` Amazon Linux 2023 instance running Vertica CE via Docker (port 5433).
* **MCP stack** (`deploy/mcp/**`, `src/**`, `tests/**`, `Dockerfile.mcp`) — Spot `t3.small` instance that pulls the MCP FastAPI server image from ECR and exposes port 8000.

Each stack has its own GitHub Actions workflow with dedicated remote Terraform state, fail-fast credential checks, and post-deploy smoke tests via AWS Systems Manager. Pushes scoped to one stack never trigger the other.

## Repository layout

```
.
├─ deploy/
│  ├─ db/
│  │  ├─ README.md
│  │  └─ terraform/
│  │     ├─ backend-bootstrap.sh
│  │     ├─ main.tf
│  │     ├─ outputs.tf
│  │     ├─ user_data_db.sh
│  │     └─ variables.tf
│  └─ mcp/
│     ├─ README.md
│     └─ terraform/
│        ├─ backend-bootstrap.sh
│        ├─ main.tf
│        ├─ outputs.tf
│        ├─ user_data_mcp.sh
│        └─ variables.tf
├─ .github/workflows/
│  ├─ db-apply-destroy.yml
│  └─ mcp-apply-destroy.yml
├─ src/mcp_vertica/
│  ├─ __init__.py
│  └─ server.py
├─ Dockerfile.mcp
├─ tests/
│  ├─ test_health.py
│  └─ test_sql_rendering.py
├─ PROMPTS.md
├─ pyproject.toml
├─ uv.lock
└─ docker-compose.yml
```

## Required repository secrets

Set these under **Settings → Secrets and variables → Actions** before running any workflow:

* `AWS_REGION` (default `ap-south-1`)
* `AWS_ACCOUNT_ID`
* Either OIDC: `AWS_ROLE_TO_ASSUME` and `AWS_OIDC_ROLE_SESSION_NAME`, or static keys: `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`

Optional:

* `ALLOWED_CIDRS` — comma-separated IPv4 CIDRs (e.g. `"49.37.x.x/32","122.166.x.x/32"`) to open ports 5433/8000 only to those networks
* `MCP_HTTP_TOKEN` — if set, the MCP HTTP server requires `Authorization: Bearer <token>`

## Workflows

### DB Stack (apply/destroy)

* Triggered by pushes to `deploy/db/**` or manual `workflow_dispatch`.
* Bootstraps the Terraform backend (`vertica-mcp-tf-<account>-<region>` bucket + DynamoDB lock table).
* Applies Terraform with defaults: Spot `t3.xlarge`, 50 GiB gp3 volume, Vertica CE image `957650740525.dkr.ecr.ap-south-1.amazonaws.com/vertica-ce:v1.0`.
* Runs `/usr/local/bin/db-smoke.sh` through SSM (executes `SELECT NOW();` via `vsql`).
* Job summary prints the public IP and a copy/paste connection string (`HOST=<ip> PORT=5433 USER=dbadmin DB=VMart`).

Destroy by dispatching the workflow with `action=destroy`.

### MCP Stack (apply/destroy + build/push)

* Triggered by pushes to `deploy/mcp/**`, `src/**`, `tests/**`, or `Dockerfile.mcp`.
* Runs `uv sync --frozen`, `ruff`, and `pytest` before touching AWS.
* Builds `Dockerfile.mcp`, pushes to `mcp-vertica` ECR repo, then applies Terraform for the MCP EC2 instance.
* Terraform reads the DB stack’s remote state to populate `DB_HOST` and writes `/opt/mcp.env` for the container.
* Smoke test hits `GET /healthz` via SSM; summary prints the MCP URL (`http://<ip>:8000`).

Destroy by dispatching with `action=destroy`.

## MCP server

The MCP FastAPI server (`src/mcp_vertica/server.py`) supports both stdio and HTTP transports. Environment variables at startup:

* `DB_HOST`, `DB_PORT` (default `5433`), `DB_USER`, `DB_PASSWORD`, `DB_NAME`
* Optional `MCP_HTTP_TOKEN` enabling bearer-token auth

Endpoints:

* `GET /healthz`
* `POST /api/render`
* `POST /api/query`

For Claude Desktop (local stdio):

```json
{
  "mcpServers": {
    "vertica-local": {
      "command": "uvx",
      "args": ["mcp-vertica", "--transport", "stdio"]
    }
  }
}
```

For remote HTTP (beta):

```json
{
  "mcpServers": {
    "vertica-remote": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "http://<MCP-PUBLIC-IP>:8000/sse"],
      "env": {
        "AUTH_HEADER": "Authorization: Bearer <MCP_HTTP_TOKEN>"
      }
    }
  }
}
```

## Local development

```bash
uv sync --frozen
uv run ruff check
uv run pytest -q
MCP_HTTP_TOKEN=local DB_HOST=localhost DB_PORT=5433 DB_USER=dbadmin DB_NAME=VMart \
  docker compose up --build
./scripts/wait-for-port.py localhost 8000 --timeout 120
curl -H "Authorization: Bearer local" http://127.0.0.1:8000/healthz
```

Destroy AWS resources when idle to minimize costs; both stacks default to Spot instances with security-group ingress restricted to `ALLOWED_CIDRS`.
