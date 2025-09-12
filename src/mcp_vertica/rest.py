from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Any, List
from .connection import VerticaConnectionManager, VerticaConfig
from .nlp import NL2SQL
from .mcp import extract_schema_from_query, extract_operation_type
import logging

log = logging.getLogger("rest")
app = FastAPI(title="mcp-vertica (local, no-auth)")

# Module level singleton connection manager
connection_manager: VerticaConnectionManager = VerticaConnectionManager()


@app.on_event("startup")
def startup_event() -> None:
    cfg = VerticaConfig.from_env()
    connection_manager.initialize_default(cfg)


@app.on_event("shutdown")
def shutdown_event() -> None:
    connection_manager.close_all()

class QueryIn(BaseModel):
    sql: str

class QueryOut(BaseModel):
    columns: List[str]
    rows: List[List[Any]]

class NLPIn(BaseModel):
    question: str
    execute: bool = True
    model: str = "llama3.1:8b"
    ollama_host: str = "http://127.0.0.1:11434"

class NlpOut(QueryOut):
    sql: str

@app.get("/api/health")
def health():
    return {"ok": True}

@app.post("/api/query", response_model=QueryOut)
def api_query(body: QueryIn):
    mgr = connection_manager
    schemas = extract_schema_from_query(body.sql)
    operation = extract_operation_type(body.sql)
    if operation:
        for schema in schemas or {"default"}:
            if not connection_manager.is_operation_allowed(schema.lower(), operation):
                raise HTTPException(status_code=403, detail=f"Operation {operation.name} not allowed for schema {schema}")
    conn = cur = None
    try:
        conn = mgr.get_connection()
        cur = conn.cursor()
        cur.execute(body.sql)
        if cur.description:
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
        else:
            # Commit to apply changes when no result set is returned
            conn.commit()
            rows = []
            cols = []
        return {"columns": cols, "rows": [list(r) for r in rows]}
    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        if cur:
            cur.close()
        if conn:
            mgr.release_connection(conn)

@app.post("/api/nlp", response_model=NlpOut)
def api_nlp(body: NLPIn):
    mgr = connection_manager
    n2s = NL2SQL(ollama_host=body.ollama_host, model=body.model)
    sql = n2s.generate_sql(mgr, body.question)
    if not body.execute:
        return {"sql": sql, "columns": [], "rows": []}
    schemas = extract_schema_from_query(sql)
    operation = extract_operation_type(sql)
    if operation:
        for schema in schemas or {"default"}:
            if not connection_manager.is_operation_allowed(schema.lower(), operation):
                raise HTTPException(status_code=403, detail=f"Operation {operation.name} not allowed for schema {schema}")
    conn = cur = None
    try:
        conn = mgr.get_connection()
        cur = conn.cursor()
        cur.execute(sql)
        if cur.description:
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
        else:
            # Commit to apply changes when no result set is returned
            conn.commit()
            rows = []
            cols = []
        return {"sql": sql, "columns": cols, "rows": [list(r) for r in rows]}
    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=400, detail=f"{e} (sql={sql})")
    finally:
        if cur:
            cur.close()
        if conn:
            mgr.release_connection(conn)

# Entrypoint for CLI
def serve_rest(host: str = "0.0.0.0", port: int = 8001):
    import uvicorn
    uvicorn.run(app, host=host, port=port)
