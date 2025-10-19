# MCP Stack

Build and deploy the MCP FastAPI server to EC2. Commits touching `deploy/mcp/**`, `src/**`, `tests/**`, or `Dockerfile.mcp` trigger `.github/workflows/mcp-apply-destroy.yml`.

## Usage

1. Configure repository secrets (`AWS_REGION`, `AWS_ACCOUNT_ID`, credentials as role or static keys). Optional: `ALLOWED_CIDRS` to restrict port 8000 and `MCP_HTTP_TOKEN` for bearer auth.
2. Push to `main` or run the **MCP Stack (apply/destroy + build/push)** workflow manually.
3. With `action=apply`, the job builds/pushes the MCP image to ECR, applies Terraform, and runs an SSM smoke test against `/healthz`. The summary prints the MCP URL.
4. Use `action=destroy` to remove the stack when finished.

The instance defaults to a Spot `t3.small`. It reads the DB private IP from the DB stack’s remote state and writes `/opt/mcp.env` for the container, including the optional `MCP_HTTP_TOKEN`.
