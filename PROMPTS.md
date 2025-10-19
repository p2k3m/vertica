# Automation prompts for Vertica MCP

The following prompts are grouped by theme so you can hand them to an automation agent or “codex” to perform incremental tasks.
They mirror the capabilities implemented in this repository.

## A. Infrastructure / Terraform

1. Create `infra/main.tf`, `variables.tf`, and `outputs.tf` for a single Vertica EC2 deployment with Spot support.
2. Add an `aws_ecr_repository` resource named `mcp-vertica` with `force_delete = true`.
3. Attach an IAM role + instance profile allowing `AmazonSSMManagedInstanceCore` and read-only ECR pulls.
4. Configure a security group exposing ports 5433 and 8000 only to `var.allowed_cidrs`.
5. Write `user_data.sh` that installs Docker, mounts `/var/lib/vertica`, and starts Docker Compose.
6. Add a `use_spot` boolean that toggles `instance_market_options`.
7. Output the instance public IP, instance ID, and ECR repository URI.
8. Create `backend-bootstrap.sh` to initialise the Terraform S3 bucket + DynamoDB lock table.
9. Provide `terraform.tfvars.example` with placeholder CIDRs and account ID.
10. Lookup the Amazon Linux 2023 AMI via `data "aws_ami"`.
11. Provision a gp3 EBS volume and attach/mount at `/var/lib/vertica`.
12. Tag all resources with `var.project`.

## B. GitHub Actions

13. Add `.github/workflows/cicd.yml` with jobs `lint-test`, `build`, `deploy`, and `destroy`.
14. Fail early if neither `AWS_ROLE_TO_ASSUME` nor static access keys are provided.
15. Use OIDC via `aws-actions/configure-aws-credentials@v4` when the role is available.
16. Build `Dockerfile.mcp`, tagging with `${{ github.sha }}` and `latest`.
17. Login to ECR and push both tags.
18. Run `infra/backend-bootstrap.sh` inside the workflow.
19. Execute `terraform init -upgrade` with the remote backend.
20. Archive the Terraform plan as an artifact.
21. Apply Terraform automatically on `push` to `main`.
22. Wait for SSM to report the instance `Online` before smoke testing.
23. Use `AWS-RunShellScript` to hit `/healthz` and ensure port 5433 is reachable.
24. Expose a manual `workflow_dispatch` path that triggers `terraform destroy`.

## C. Docker & Compose

25. Create `Dockerfile.mcp` that installs dependencies with `uv` and exposes port 8000.
26. Add a container `HEALTHCHECK` against `http://127.0.0.1:8000/healthz`.
27. Provide `docker-compose.yml` for local Vertica CE + MCP development.
28. Persist Vertica data under `./_data/vertica`.
29. Add `.dockerignore` for build artefacts and local data.
30. Generate `infra/compose.remote.yml` for the EC2 runtime.
31. Inject `MCP_HTTP_TOKEN` only in the remote compose file.
32. Ensure the remote MCP container connects to Vertica using `172.17.0.1:5433`.

## D. MCP server code

33. Replace inline SQL with `sql_loader.load_sql()`.
34. Add `AuthMiddleware` enforcing `MCP_HTTP_TOKEN` when set.
35. Implement `/healthz`, returning `{"status": "ok"}`.
36. Keep SSE transport available for local development (`run_sse`).
37. Keep HTTP transport for server mode (`run_http`).
38. Log parameter tuples at debug level instead of full SQL strings.
39. Sanitize identifiers and only format table names, never parameters.
40. Enforce per-schema allowlists driven by environment variables.
41. Implement `_is_stale` handling ISO timestamps and Unix epochs.
42. Block DDL/DML unless allowed by schema or global permissions.
43. Return provenance metadata with every tool response.
44. Add pagination via `LIMIT %s` to list-style queries.
45. Emit error payloads with provenance fallback (`row_count = 0`).
46. Configure CORS via `ALLOWED_ORIGINS`.

## E. SQL files

47. Create `get_event_application.sql` for distinct applications.
48. Create `cis_for_business_service_events.sql` joining CI tables.
49. Add `collection_for_ci.sql` unioning pod/node/container collections.
50. Provide `collection_members_nodes.sql`.
51. Provide `collection_members_pods.sql`.
52. Provide `collection_members_containers.sql`.
53. Provide `ci_facts_node.sql`.
54. Provide `ci_facts_pod.sql`.
55. Provide `ci_facts_container.sql`.
56. Provide `security_alerts_last7d.sql`.
57. Provide `search_tables.sql`.
58. Provide `search_columns.sql`.
59. Provide `list_views.sql`.
60. Provide `list_indexes.sql`.
61. Provide `get_event_ci.sql`.

## F. Testing

62. Add `tests/test_utils.py` covering `_sanitize_ident`, `_qual`, and `_is_stale`.
63. Add `tests/test_sql_exists.py` ensuring SQL templates are present and non-empty.
64. Ensure the MCP module imports successfully under pytest.
65. Configure `pytest.ini` to silence irrelevant deprecation warnings.
66. Add `ruff.toml` with repository lint rules.
67. Fail the CI pipeline if Ruff reports issues.
68. Guard against dangerous SQL by checking for `;--` patterns in tests or CI.
69. Provide a stub test demonstrating `execute_query("SELECT 1")` using a fake manager.
70. Skip database-dependent tests when Vertica env vars are missing.
71. Upload pytest results as workflow artifacts.

## G. Smoke / SSM

72. Run `curl -fsS http://127.0.0.1:8000/healthz` via SSM.
73. Verify `docker ps` shows both containers.
74. Check port 5433 with `timeout 5 bash -c 'echo > /dev/tcp/127.0.0.1/5433'`.
75. Optionally run `vsql -U dbadmin -d VMart -c "select 1"` if available.
76. Collect `/var/log/cloud-init-output.log` via SSM when failures occur.
77. Fail the pipeline if any smoke command fails.

## H. Security

78. Fail the workflow if `allowed_cidrs` includes `0.0.0.0/0` and `MCP_HTTP_TOKEN` is empty.
79. Generate a random `MCP_HTTP_TOKEN` during manual dispatch when the secret is absent.
80. Ensure the EC2 role only has ECR pull permissions.
81. Pin GitHub Actions versions (no `@main`).
82. Pin `python:3.12-slim` by digest in the Dockerfile.
83. Run containers as non-root.

## I. Observability

84. Add `/api/info` reporting server version, pool size, and schema allowlists.
85. Emit connection pool metrics every 60 seconds.
86. Upload recent Docker logs as artifacts when jobs fail.
87. Grab EC2 console output on failure for debugging.
88. Document how to store database credentials in SSM Parameter Store for future use.

## J. Developer experience

89. Provide `Makefile` targets (`install`, `test`, `fmt`, `lint`, `local-up`, `local-down`, `destroy`).
90. Add `.vscode/launch.json` for debugging the MCP server locally.
91. Offer an `uvx mcp-vertica --stdio` command reference for Claude Desktop.
92. Add `scripts/seed_itsm.py` wiring for optional demo schema (already present).
93. Ship `scripts/wait-for-port.py` to manage container boot order.
94. Keep `smithery.yaml` pointing to the MCP HTTP endpoint.

## K. Claude Desktop enablement

95. Document Claude Desktop stdio setup with command JSON snippets.
96. Document Smithery remote configuration for HTTP MCP.
97. Provide macOS and Windows commands for launching the server locally.
98. Include troubleshooting notes for failed server launches.
99. Link to FastMCP’s HTTP mode documentation.

## L. FinOps & sizing

100. Document the Spot toggle and how to switch to On-Demand.
101. Show how to resize the EBS volume safely.
102. List instance type recommendations (why 16 GiB RAM helps Vertica).
103. Explain why there is no NAT/ALB in this footprint.
104. Suggest stopping the instance daily when idle.
105. Document the `workflow_dispatch: destroy` path.

## M. Extra polish

106. Add `X-Request-Id` headers and log them server-side.
107. Include `server_time_utc` in provenance payloads.
108. Allow a `schema` override parameter for demo scenarios.
109. Return HTTP 429 when too many concurrent queries are running.
110. Honour `MCP_READ_ONLY` env to disable DDL/DML regardless of allowlists.
111. Offer CSV responses when clients send `Accept: text/csv`.
112. Publish a `/tools.json` endpoint listing tool names and descriptions.
113. Provide a lightweight `/_alive` TCP probe endpoint.
114. Expose `make fmt` running `ruff --fix`.
115. Document the ECS/EKS upgrade path.

