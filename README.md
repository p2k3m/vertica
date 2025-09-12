# mcp-vertica — Local NLP + REST for Vertica (no auth)

This runs **entirely on your laptop**: Vertica CE via Docker, a local REST API, and a terminal **NLP→SQL** command powered by a local LLM (Ollama). No auth, bound on `0.0.0.0` for convenience.

> ⚠️ Security is **intentionally disabled** for local demos. Do not expose to the public internet.

## Prerequisites

- **Docker Desktop**
- **Python 3.12+**
- **uv** (recommended) or `pip`
- **Ollama** (for local LLM)
  - **Mac**: `brew install ollama` → `ollama serve &` → `ollama pull llama3.1:8b`
  - **Windows**: install Ollama app → run “Ollama” → in PowerShell: `ollama pull llama3.1:8b`
- (Optional) A Vertica instance; we provide Docker.

## 1) Start Vertica locally

```bash
docker compose up -d
# Wait until healthy (30–60s)
docker ps
```

Defaults:

Host: localhost

Port: 5433

Database: VMart

User: dbadmin

Password: (empty)

## 2) Install & configure mcp-vertica
```bash
# Mac/Linux (uv)
uv sync
# Or pip:
# python -m venv .venv && source .venv/bin/activate
# pip install -e .
```

Set env (Mac/Linux bash or zsh):

```bash
export VERTICA_HOST=127.0.0.1
export VERTICA_PORT=5433
export VERTICA_DATABASE=VMart
export VERTICA_USER=dbadmin
export VERTICA_PASSWORD=""
export VERTICA_CONNECTION_LIMIT=10
```

Windows (PowerShell):

```powershell
$env:VERTICA_HOST="127.0.0.1"
$env:VERTICA_PORT="5433"
$env:VERTICA_DATABASE="VMart"
$env:VERTICA_USER="dbadmin"
$env:VERTICA_PASSWORD=""
$env:VERTICA_CONNECTION_LIMIT="10"
```

### Operation permissions

Global defaults for SQL operations can be controlled with environment variables:

```bash
export ALLOW_SELECT_OPERATION=true
export ALLOW_INSERT_OPERATION=false
export ALLOW_UPDATE_OPERATION=false
export ALLOW_DELETE_OPERATION=false
export ALLOW_DDL_OPERATION=false
```

You can override these on a per-schema basis using comma-separated
`schema:true|false` pairs:

```bash
export SCHEMA_SELECT_PERMISSIONS="public:true,itsm:false"
# SCHEMA_INSERT_PERMISSIONS, SCHEMA_UPDATE_PERMISSIONS,
# SCHEMA_DELETE_PERMISSIONS and SCHEMA_DDL_PERMISSIONS work the same way
```

If no schema permissions are configured, the server logs a notice and all
operations (SELECT, INSERT, UPDATE, DELETE and DDL) fall back to the global
settings.

## 3) Seed ITSM/CMDB sample data
```bash
python scripts/seed_itsm.py
# Creates schemas itsm/cmdb and loads ~2k incidents + CIs/changes/relations
```

## 4) REST API (no auth)
```bash
uvx mcp-vertica serve-rest --host 0.0.0.0 --port 8001
```

Test:

```bash
curl http://127.0.0.1:8001/api/health
curl -X POST http://127.0.0.1:8001/api/query \
  -H 'Content-Type: application/json' \
  -d '{"sql":"SELECT COUNT(*) AS n FROM itsm.incident;"}'
```

NLP endpoint:

```bash
curl -X POST http://127.0.0.1:8001/api/nlp \
  -H 'Content-Type: application/json' \
  -d '{"question":"Top 5 incident categories this month", "execute": true}'
```

## 5) NLP from terminal

Start Ollama in background (if not already):

```bash
ollama serve &
ollama pull llama3.1:8b
```

Examples:

```bash
# Ask anything; will generate Vertica SQL and run it
uvx mcp-vertica nlp ask "Top 5 incident categories this month by count"

# Create a table (mutations allowed)
uvx mcp-vertica nlp ask "Create table staging.high_prio_incidents as P1 incidents last 7 days"

# Dry-run (just show SQL)
uvx mcp-vertica nlp ask --dry-run "List incidents joined to CI class and change window overlap"

# Similar incidents
uvx mcp-vertica nlp similar --incident-id INC000123
uvx mcp-vertica nlp similar --text "database timeout in payment service" --top-k 10
```

## 6) SSE MCP server (unchanged)
```bash
uvx mcp-vertica --port 8000  # runs SSE (0.0.0.0)
```

## Troubleshooting

If MCP client can’t connect: uv cache clean and retry.

If Vertica not ready: `docker logs vertica-ce` and re-run after healthy. To
check databases:

```bash
admintools -t list_all_dbs
# Name    | Owner   | State
# VMart   | dbadmin | Running
```

Inspect a specific database:

```bash
admintools -t list_db -d VMart
# Database: VMart
# State: Running
# v_vmart_node0001 (UP)
```

If Ollama fails: ensure ollama serve is running and you pulled a model.

## License

MIT
