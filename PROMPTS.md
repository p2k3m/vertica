### Category: Infra/Provisioning (20)

1. "Create a Terraform variable to toggle Spot instances and wire it into `aws_instance.instance_market_options`."
2. "Add a variable to switch between `t3.xlarge` and `m6i.xlarge` and set a validation rule that memory must be ≥16GB."
3. "Split security group ingress so ports 5433 and 8000 use the same `allowed_cidrs` list via a dynamic block."
4. "Output both `public_ip` and `mcp_http_url` from Terraform in JSON for the pipeline."
5. "Add an `ALLOWED_CIDR` repo variable and flow it into Terraform via `-var` in the workflow."
6. "Enable SSM Session Manager by attaching `AmazonSSMManagedInstanceCore` to the EC2 role."
7. "Add a `volume_size_gb` var and map to `ebs_block_device`."
8. "Pin AMI to `al2023 kernel 6.1 x86_64` and explain why (compatibility with Vertica)."
9. "Add a toggle to disable public IP for private deployments and show how to reach via SSM port forwarding."
10. "Expose `instance_id` as an output and document `aws ssm start-session` examples."
11. "Create a TF local-exec that echoes `docker ps` via SSM to validate container boot."
12. "Inject `MCP_HTTP_TOKEN` into user_data and enforce header auth in the HTTP app."
13. "Add CloudWatch agent config to ship `/var/log/user-data.log`."
14. "Create an IAM policy limited to **read-only** ECR + SSM; no wildcards."
15. "Set termination protection false; explain how to tear down with `terraform destroy`."
16. "Parameterise subnet selection via a `subnet_id` var with default = first default subnet."
17. "Add a secondary EBS volume for WAL and mount at `/var/lib/vertica/wal`."
18. "Switch `use_spot` to false for demos that require stability."
19. "Template the compose file with `envsubst` for dynamic DB names."
20. "Guard user_data with `set -Eeuo pipefail` and log redirection."

### Category: Docker & Compose (12)

21. "Add `ulimits: nofile: 65536` to Vertica service."
22. "Make MCP depend on Vertica so health wait is linear."
23. "Publish only port 8000 on MCP; restrict Vertica to SG allowlist."
24. "Add a named volume `vertica_data` for local dev."
25. "Separate `compose.remote.yml` (server) from local compose."
26. "Parametrise Vertica credentials via `.env`."
27. "Enable restart policy `unless-stopped` for both services."
28. "Add healthcheck commands to both services."
29. "Document how to rotate `MCP_HTTP_TOKEN` without downtime."
30. "Push the MCP image with tag `${{ github.sha }}` and also `latest`."

### Category: MCP Server & SQL (20)

31. "Load SQL templates with a `sql_loader` and restrict substitutions to `schema`, `view_bs_to_ci`."
32. "Add `/healthz` route using Starlette that returns `{ok:true}`."
33. "Ensure `_operation_type` blocks DDL/DML unless allow-listed."
34. "Return provenance `{sql_or_view, params, as_of_ts, row_count}` for all tools."
35. "Use `_is_stale` heuristic for CI facts when timestamps are old."
36. "Add `search_tables`, `search_columns` generic helpers using `v_catalog`."
37. "Add `execute_query` with strict read-only policy by default."
38. "Set default `SCHEMA_DEFAULT` from `VERTICA_SCHEMA` env var."
39. "Expose server version via `mcp._mcp_server.version`."
40. "Add CORS middleware for HTTP mode with permissive defaults."

### Category: Testing (10)

41. "Write a pytest to assert all required SQL files exist."
42. "Write a test for the `/healthz` handler."
43. "Mock Vertica cursor to test `_rows_to_dicts`."
44. "Add a unit test verifying `_operation_type` classification."
45. "Create a test ensuring `_qual` rejects invalid identifiers."
46. "Add a contract test that `cis_for_business_service_events.sql` has four `%s` placeholders."
47. "Add smoke test step to curl `/api/info`."
48. "Add smoke test step to curl `/healthz`."
49. "Fail fast CI on ruff lint errors."
50. "Add CI matrix for Python 3.12 and 3.13."

### Category: Pipeline (15)

51. "Validate secrets at the start of the workflow and exit with clear errors."
52. "Use `aws-actions/amazon-ecr-login@v2` to simplify ECR login."
53. "Auto-create ECR repo if missing."
54. "Pass `MCP_HTTP_TOKEN` into Terraform as `TF_VAR_mcp_http_token`."
55. "Emit TF outputs to JSON and export to GITHUB_ENV."
56. "Add a dependent job `smoke` that waits for `/healthz`."
57. "Cache `~/.cache/uv` between runs for faster builds."
58. "Add concurrency group to prevent parallel applies."
59. "Trigger only on `main` pushes; add `workflow_dispatch` for manual."
60. "Add environment protection rules for `prod` branch."

### Category: Cost & Ops (12)

61. "Default to Spot; stop on interruption to preserve EBS data."
62. "Expose a `disable_public_ip` var to force SSM-only access."
63. "Document how to `terraform destroy` to avoid zombie costs."
64. "Set `volume_type=gp3` with modest IOPS; bump only if needed."
65. "Use `t3.xlarge` baseline credits; monitor `CPUCreditBalance`."
66. "Restrict SG ingress to a `/32` when demoing from a fixed IP."
67. "Use `aws budgets` CLI to create a small budget with alert."
68. "Stop instance overnight with an EventBridge schedule (optional)."
69. "Prefer single-AZ to avoid cross-AZ data charges."
70. "Keep CloudWatch logs basic; avoid retention >7 days for POC."

### Category: Troubleshooting (13)

71. "Check `/var/log/user-data.log` when containers don’t start."
72. "Run `docker logs mcp_vertica` and `docker logs vertica_ce` via SSM."
73. "Verify ECR cross-account permissions if the Vertica image fails to pull."
74. "Ensure AMI is **x86_64** if the image is built for Intel."
75. "Increase `instance_type` if Vertica OOMs (m6i.xlarge)."
76. "Open SG port 8000 to your IP if health checks fail from GitHub."
77. "Use `curl http://127.0.0.1:8000/api/info` on the instance to isolate SG issues."
78. "Confirm mount `/var/lib/vertica` is present and writable."
79. "Check `VERTICA_*` envs in the MCP container."
80. "Validate SQL files load by enabling debug logs in `sql_loader`."
81. "Run `terraform taint aws_instance.mcp` to force re-provision."
82. "Clear Docker cache: `docker system prune -a` if disk fills."

### Category: Claude Desktop usage (12)

83. "Register the HTTP MCP at `http://<dns>:8000` with header `X-Api-Key`."
84. "Switch to stdio transport on macOS with `uvx mcp-vertica --transport stdio`."
85. "Pass DB params via query string: `?host=vertica&dbPort=5433&database=vmart&user=dbadmin&password=password`."
86. "Call `get_event_application(limit=10)` to list apps."
87. "Pivot to `cis_for_business_service(bs_name='Checkout')`."
88. "Resolve a pod’s cluster: `gke_identify_pod_cluster('POD_ID')`."
89. "List collection members: `collection_members('CLUSTER')`."
90. "Show CI facts: `ci_facts(ci_id='CI123', fact_keys=['compute_status','zone'])`."
91. "Search tables: `search_tables('gke')`."
92. "Search columns: `search_columns('cmdb_id')`."
93. "Run a controlled `execute_query('SELECT 1')` as a sanity check."
94. "Fetch event CIs: `get_event_ci(limit=20)`."

### Category: Security (8)

95. "Use `MCP_HTTP_TOKEN` and check for the header in a simple Starlette middleware."
96. "Restrict SG to your `/32` when demoing to executives."
97. "Do **not** open SSH; use SSM only."
98. "Avoid storing secrets in the repo; use Actions secrets."
99. "Pin Docker base image to `python:3.12-slim` and update monthly."
100. "Run the MCP container as a non-root user."
101. "Set `VERTICA_SSL=false` for POC; document enabling TLS later."
102. "Add `X-Frame-Options: DENY` and `X-Content-Type-Options: nosniff` headers via middleware (optional)."
