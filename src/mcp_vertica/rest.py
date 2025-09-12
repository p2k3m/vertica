from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Any, List
from .connection import VerticaConnectionManager, VerticaConfig
from .nlp import NL2SQL
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
    conn = cur = None
    try:
        conn = mgr.get_connection()
        cur = conn.cursor()
        cur.execute(body.sql)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description] if cur.description else []
        return {"columns": cols, "rows": [list(r) for r in rows]}
    except Exception as e:
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
    conn = cur = None
    try:
        conn = mgr.get_connection()
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description] if cur.description else []
        return {"sql": sql, "columns": cols, "rows": [list(r) for r in rows]}
    except Exception as e:
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
