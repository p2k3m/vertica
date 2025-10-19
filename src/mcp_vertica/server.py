import os
import pathlib
import re
from typing import Any, Dict

import vertica_python
from fastapi import FastAPI, Header, HTTPException
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from pydantic import BaseModel, Field
from tenacity import retry, stop_after_attempt, wait_fixed

SQL_DIR = pathlib.Path(__file__).resolve().parents[2] / "sql"
V_HOST = os.environ.get("DB_HOST") or os.environ.get("VERTICA_HOST", "localhost")
V_PORT = int(os.environ.get("DB_PORT") or os.environ.get("VERTICA_PORT", "5433"))
V_USER = os.environ.get("DB_USER") or os.environ.get("VERTICA_USER", "dbadmin")
V_PASS = os.environ.get("DB_PASSWORD") or os.environ.get("VERTICA_PASSWORD", "")
V_DB = os.environ.get("DB_NAME") or os.environ.get("VERTICA_DATABASE", "vertica")
MCP_TOKEN = os.environ.get("MCP_HTTP_TOKEN", "")

jinja = Environment(
    loader=FileSystemLoader(str(SQL_DIR)),
    undefined=StrictUndefined,
    autoescape=False,
)
SAFE_NAME = re.compile(r"^[a-zA-Z0-9_\-]+\.sql$")


class RenderRequest(BaseModel):
    template: str = Field(..., description="SQL template filename in sql/")
    params: Dict[str, Any] = Field(default_factory=dict)


class QueryRequest(RenderRequest):
    limit: int = Field(1000, ge=1, le=10000)


def _require_auth(authorization: str | None) -> None:
    if MCP_TOKEN and authorization != f"Bearer {MCP_TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized")


@retry(stop=stop_after_attempt(5), wait=wait_fixed(2))
def _connect():
    return vertica_python.connect(
        host=V_HOST,
        port=V_PORT,
        user=V_USER,
        password=V_PASS,
        database=V_DB,
        ssl=False,
        connection_timeout=5,
    )


app = FastAPI()


@app.get("/healthz")
def healthz() -> Dict[str, Any]:
    return {"ok": True, "sql_dir": str(SQL_DIR)}


@app.post("/api/render")
def render(req: RenderRequest, authorization: str | None = Header(default=None)) -> Dict[str, Any]:
    _require_auth(authorization)
    if not SAFE_NAME.match(req.template):
        raise HTTPException(status_code=400, detail="Invalid template name")
    tpl = jinja.get_template(req.template)
    sql = tpl.render(**req.params)
    return {"sql": sql}


@app.post("/api/query")
def query(req: QueryRequest, authorization: str | None = Header(default=None)) -> Dict[str, Any]:
    _require_auth(authorization)
    if not SAFE_NAME.match(req.template):
        raise HTTPException(status_code=400, detail="Invalid template name")
    tpl = jinja.get_template(req.template)
    sql = tpl.render(**req.params)
    sql_wrapped = f"SELECT * FROM ( {sql} ) t LIMIT {int(req.limit)}"
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute(sql_wrapped)
        cols = [desc[0] for desc in cur.description]
        rows = cur.fetchall()
    return {"columns": cols, "rows": rows, "row_count": len(rows), "sql": sql_wrapped}


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
