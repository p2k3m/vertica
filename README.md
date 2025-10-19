# Vertica MCP on AWS – Drop-in Pack

This repository delivers a low-cost, single-command deployment for Vertica CE and the Vertica MCP server. It includes Terraform infrastructure, a GitHub Actions deployment pipeline, container tooling for local development, and 100+ automation prompts for MCP-aware agents.

## Repository layout

```
.
├─ infra/                      # Terraform + cloud-init user_data
│  ├─ backend-bootstrap.sh     # Helper for creating S3/DDB backend
│  ├─ main.tf                  # Security group, IAM, EC2, EBS, outputs
│  ├─ variables.tf             # Region, instance type, Spot toggle, etc.
│  ├─ outputs.tf               # MCP URL export
│  └─ user_data.sh             # Installs Docker, writes compose file, boot
├─ sql/                        # Parameterised SQL templates (loaded by MCP)
├─ src/mcp_vertica/            # MCP server package (FastMCP + Vertica tools)
├─ scripts/wait-for-port.py    # Lightweight TCP wait helper
├─ docker-compose.yml          # Local Vertica CE + MCP stack
├─ Dockerfile.mcp              # MCP container image definition
├─ .github/workflows/deploy.yml# CI → ECR → Terraform → smoke tests
├─ PROMPTS.md                  # 100+ ready-to-run automation prompts
└─ README.md                   # This document
```

## Prerequisites

Populate these GitHub Secrets (`Settings → Secrets and variables → Actions`):

| Name | Type | Purpose |
| --- | --- | --- |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | Secret | Required for pushing to ECR + Terraform provisioning |
| `AWS_ACCOUNT_ID` | Secret | Used for ECR repo/image tagging |
| `MCP_HTTP_TOKEN` | Secret (optional) | Enables HTTP auth via `X-Api-Key` |

Optional repository variables:

| Name | Default | Description |
| --- | --- | --- |
| `VERTICA_IMAGE_URI` | `957650740525.dkr.ecr.ap-south-1.amazonaws.com/vertica-ce:v1.0` | Override Vertica CE image |
| `ALLOWED_CIDR` | `0.0.0.0/0` | CIDR block allowed through the security group |

> The workflow fails fast if required secrets are missing.

## Local development

1. **Install prerequisites**: Docker Desktop, Python 3.12+, [`uv`](https://github.com/astral-sh/uv).
2. **Install dependencies & run tests**
   ```bash
   uv sync --frozen
   uv run ruff check
   uv run pytest -q
   ```
3. **Launch Vertica CE + MCP locally**
   ```bash
   docker compose up --build -d
   ./scripts/wait-for-port.py localhost 8000 --timeout 120 --interval 2
   curl http://127.0.0.1:8000/healthz
   ```
4. **Connect Claude Desktop (stdio)**
   ```json
   {
     "name": "vertica-local",
     "command": ["uvx", "mcp-vertica", "--transport", "stdio"],
     "workingDirectory": "."
   }
   ```

The local stack mirrors the AWS deployment with Vertica CE on port `5433` and MCP HTTP transport on port `8000`.

## AWS deployment pipeline

Pushing to `main` runs `.github/workflows/deploy.yml`:

1. **ci** – Installs dependencies via `uv`, runs Ruff + pytest.
2. **build_and_push_mcp** – Builds `Dockerfile.mcp`, pushes `${AWS_ACCOUNT_ID}.dkr.ecr…/mcp-vertica:${{ github.sha }}` after ensuring the ECR repo exists.
3. **infra** – Applies Terraform from `infra/` (default `ap-south-1`, `t3.xlarge` Spot, gp3 volume). Outputs are captured to `infra/tfout.json`.
4. **smoke** – Waits for `/healthz`, then curls `/api/info` using the public DNS from Terraform outputs.

### Terraform highlights

* Default VPC / first subnet in `ap-south-1`.
* Security group exposes Vertica (5433) and MCP (8000) to `var.allowed_cidrs`.
* EC2 role with SSM and read-only ECR permissions.
* Spot capacity (stop-on-interrupt) by default; override via `var.use_spot`.
* gp3 data volume mounted at `/var/lib/vertica`.
* `user_data.sh` installs Docker, logs into ECR, writes `compose.remote.yml`, runs Docker Compose, and waits for `/healthz`.

### Outputs

Terraform emits:

* `public_ip`
* `public_dns`
* `mcp_http_url = http://<public-dns>:8000`

Use the `mcp_http_url` value when registering the MCP with Claude Desktop (HTTP transport) or Smithery. Include the `X-Api-Key` header if you configured `MCP_HTTP_TOKEN`.

## Security & cost guardrails

* Defaults to a single `t3.xlarge` Spot instance. Set `use_spot=false` or change `instance_type` for stability.
* gp3 `volume_size_gb=100` – adjust via Terraform variable if datasets are smaller.
* Security group defaults to `0.0.0.0/0`; narrow this with `ALLOWED_CIDR` or direct Terraform variables.
* HTTP auth token support via `MCP_HTTP_TOKEN`.
* `backend-bootstrap.sh` bootstraps S3 + DynamoDB for Terraform state.

Destroy resources when finished:
```bash
terraform -chdir=infra destroy -auto-approve
```

## SQL templates & tools

All Vertica SQL lives under `sql/` and is loaded via `SQL.load()`/`SQL.render()`. Only `{schema}` and `{view_bs_to_ci}` substitutions are permitted. The MCP tools cover:

* Business service CI lookup via events or the `v_bs_to_ci_edges` view
* Collection discovery and membership for GKE pods/nodes/containers
* CI facts (node/pod/container/security alerts)
* Event browsing helpers (`get_event_application`, `get_event_ci`)
* GKE mapping helpers (`gke_identify_*`)
* Repeat issue ranking based on duplicate counts, age, and cluster match

Each tool response includes provenance metadata (`sql_or_view`, parameters, row count, `as_of_ts`). The `/healthz` handler lives in `mcp_vertica.health` and is mounted for both HTTP and SSE transports.

## Claude Desktop (remote HTTP)

Example HTTP registration:
```json
{
  "name": "vertica-aws",
  "type": "http",
  "url": "http://PUBLIC_DNS:8000",
  "headers": { "X-Api-Key": "${MCP_HTTP_TOKEN}" },
  "query": {
    "host": "vertica",
    "dbPort": "5433",
    "database": "VMart",
    "user": "dbadmin",
    "password": "password",
    "ssl": "false",
    "sslRejectUnauthorized": "false",
    "connectionLimit": "8"
  }
}
```
Replace `PUBLIC_DNS` with the Terraform output. Claude Desktop on macOS and Windows can use this profile directly or through Smithery.

## Prompts

`PROMPTS.md` ships with 102 categorized prompts (infra, Docker, MCP tooling, pipeline, security, troubleshooting, Claude usage). Use them to drive automated refactors or runbooks.

## Troubleshooting

* Check `/var/log/user-data.log` on the instance (captured by the user-data logger).
* Use AWS SSM Session Manager (`aws ssm start-session --target <instance-id>`) for interactive debugging.
* Validate Docker containers: `docker ps`, `docker logs mcp_vertica`, `docker logs vertica_ce`.
* Verify health: `curl -H 'X-Api-Key: <token>' http://<public-dns>:8000/healthz`.

Happy querying!
