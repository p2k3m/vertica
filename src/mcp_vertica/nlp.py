import os
import requests
import re
from dataclasses import dataclass
from typing import List, Optional
from .connection import VerticaConnectionManager

SYS_PROMPT = """You are a SQL generator for Vertica.
- Dialect: Vertica SQL. Prefer CTEs, clear aliases, and LIMITs for previews.
- Input: a natural-language question + a schema snapshot.
- Output: ONLY a single SQL statement (no markdown, no comments, no explanations).
- You MAY produce DDL/DML if the user asks (CREATE/ALTER/INSERT/UPDATE/DELETE).
- Prefer explicit column lists; avoid SELECT * in final output.
- Use Vertica date/time functions where needed.
- Keep it deterministic and syntactically valid for Vertica.
"""

EXAMPLES = [
  {
    "q": "Top 5 incident categories this month by count",
    "sql": "WITH month_inc AS (SELECT category FROM itsm.incident WHERE opened_at >= DATE_TRUNC('month', NOW())) SELECT category, COUNT(*) AS cnt FROM month_inc GROUP BY category ORDER BY cnt DESC LIMIT 5;"
  },
  {
    "q": "Create a new table staging.high_prio_incidents with P1 incidents opened in last 7 days",
    "sql": "CREATE TABLE staging.high_prio_incidents AS SELECT id, opened_at, priority, short_desc FROM itsm.incident WHERE priority='P1' AND opened_at >= NOW() - INTERVAL '7 days';"
  },
]

@dataclass
class NL2SQL:
    ollama_host: str = "http://127.0.0.1:11434"
    model: str = "llama3.1:8b"
    schemas: Optional[List[str]] = None

    def __post_init__(self):
        if self.schemas is None:
            env = os.getenv("VERTICA_NLP_SCHEMAS")
            if env:
                self.schemas = [s.strip() for s in env.split(",") if s.strip()]

    def _schema_snapshot(self, mgr: VerticaConnectionManager) -> str:
        conn = cur = None
        try:
            conn = mgr.get_connection()
            cur = conn.cursor()

            cur.execute("SELECT schema_name FROM v_catalog.schemata")
            db_schemas = [r[0] for r in cur.fetchall()]

            # Start with user override if provided; otherwise all DB schemas
            if self.schemas:
                schema_names = [s.lower() for s in self.schemas]
            else:
                schema_names = [s.lower() for s in db_schemas]
                # Optional filter based on connection config
                if mgr.config and mgr.config.schema_permissions:
                    allowed = {k.lower() for k in mgr.config.schema_permissions.keys()}
                    if allowed:
                        schema_names = [s for s in schema_names if s in allowed]

            if not schema_names:
                return ""

            placeholders = ",".join(["%s"] * len(schema_names))
            cur.execute(
                f"""
                SELECT table_schema, table_name, column_name, data_type
                FROM v_catalog.columns
                WHERE LOWER(table_schema) IN ({placeholders})
                ORDER BY table_schema, table_name, ordinal_position
                """,
                schema_names,
            )
            rows = cur.fetchall()
            lines = []
            for s, t, c, dt in rows:
                lines.append(f"{s.lower()}.{t.lower()}.{c.lower()} {dt}")
            return "\n".join(lines[:800])  # cap to keep prompt small
        finally:
            if cur:
                cur.close()
            if conn:
                mgr.release_connection(conn)

    def generate_sql(self, mgr: VerticaConnectionManager, question: str) -> str:
        schema_txt = self._schema_snapshot(mgr)
        examples = "\n".join([f"Q: {e['q']}\nSQL: {e['sql']}" for e in EXAMPLES])
        user = f"""Question: {question}

Schema:
{schema_txt}

Return only SQL."""
        payload = {
          "model": self.model,
          "prompt": f"{SYS_PROMPT}\n\n{examples}\n\n{user}",
          "stream": False,
          "options": {"temperature": 0.1}
        }
        try:
            r = requests.post(f"{self.ollama_host}/api/generate", json=payload, timeout=120)
            r.raise_for_status()
        except requests.RequestException as e:
            raise RuntimeError(f"Failed to generate SQL: {e}") from e
        text = r.json().get("response","").strip()
        # Extract the first semicolon-terminated SQL if model babbles
        m = re.search(r"(?is)(.*?;)", text)
        return (m.group(1) if m else text).strip()

# Similar Incidents (TF-IDF in Python)
class SimilarIncidents:
    def __init__(self, top_k: int = 5):
        self.top_k = top_k

    def query(self, mgr: VerticaConnectionManager, text: Optional[str] = None, incident_id: Optional[str] = None):
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
        conn = cur = None
        try:
            conn = mgr.get_connection()
            cur = conn.cursor()
            cur.execute(
                "SELECT id, COALESCE(short_desc,'') || ' ' || COALESCE(description,'') AS txt FROM itsm.incident"
            )
            rows = cur.fetchall()
            corpus_ids = [r[0] for r in rows]
            corpus_txt = [r[1] for r in rows]
            if len(corpus_txt) < 2:
                return []
            if incident_id:
                if incident_id not in corpus_ids:
                    raise ValueError(f"Incident {incident_id} not found")
                seed_txt = corpus_txt[corpus_ids.index(incident_id)]
            else:
                if not text:
                    raise ValueError("Provide text or incident_id")
                seed_txt = text
            vec = TfidfVectorizer(min_df=min(2, len(corpus_txt)), max_features=5000)
            X = vec.fit_transform(corpus_txt)
            xq = vec.transform([seed_txt])
            sims = cosine_similarity(xq, X).ravel()
            top_idx = sims.argsort()[::-1][: self.top_k + 1]
            results = []
            for i in top_idx:
                if incident_id and corpus_ids[i] == incident_id:
                    continue
                results.append({"id": corpus_ids[i], "similarity": float(sims[i])})
                if len(results) == self.top_k:
                    break
            if not results:
                return []
            # Fetch fix notes/status for output
            placeholders = ",".join(["%s"] * len(results))
            cur.execute(
                f"SELECT id, status, closed_at, assignment_group, short_desc "
                f"FROM itsm.incident WHERE id IN ({placeholders})",
                [r["id"] for r in results],
            )
            recs = cur.fetchall()
            by_id = {
                r[0]: {
                    "id": r[0],
                    "status": r[1],
                    "closed_at": r[2],
                    "assignment_group": r[3],
                    "short_desc": r[4],
                }
                for r in recs
            }
            for r in results:
                r.update(by_id.get(r["id"], {}))
            return results
        finally:
            if cur: cur.close()
            if conn: mgr.release_connection(conn)
