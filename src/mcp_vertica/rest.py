from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Any, List, Optional
from .connection import VerticaConnectionManager, VerticaConfig
from .nlp import NL2SQL
import logging

log = logging.getLogger("rest")
app = FastAPI(title="mcp-vertica (local, no-auth)")

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

def _manager() -> VerticaConnectionManager:
    cfg = VerticaConfig.from_env()
    mgr = VerticaConnectionManager()
    mgr.initialize_default(cfg)
    return mgr

@app.get("/api/health")
def health():
    return {"ok": True}

@app.post("/api/query", response_model=QueryOut)
def api_query(body: QueryIn):
    mgr = _manager()
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
        if cur: cur.close()
        if conn: mgr.release_connection(conn)

@app.post("/api/nlp", response_model=NlpOut)
def api_nlp(body: NLPIn):
    mgr = _manager()
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
        if cur: cur.close()
        if conn: mgr.release_connection(conn)

# Entrypoint for CLI
def serve_rest(host: str = "0.0.0.0", port: int = 8001):
    import uvicorn
    uvicorn.run(app, host=host, port=port)
