import os
import requests
import re
import heapq
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
        try:
            data = r.json()
        except ValueError as e:
            raise RuntimeError("Failed to parse NL2SQL response") from e
        text = data.get("response")
        if not text:
            raise RuntimeError("NL2SQL service returned no SQL")
        text = text.strip()
        # Extract the first semicolon-terminated SQL if model babbles
        m = re.search(r"(?is)(.*?;)", text)
        return (m.group(1) if m else text).strip()

# Similar Incidents (TF-IDF in Python)
class SimilarIncidents:
    def __init__(self, top_k: int = 5):
        self.top_k = top_k

    def query(
        self,
        mgr: VerticaConnectionManager,
        text: Optional[str] = None,
        incident_id: Optional[str] = None,
        lookback_days: int = 90,
        limit: int = 10000,
    ):
        """Return incidents similar to the given text or incident.

        The incident corpus is streamed from Vertica in 1000-row chunks. Each
        chunk is vectorized with TF–IDF and compared against the seed text, so
        only the top ``top_k`` matches are kept in memory. This avoids loading
        the entire result set at once.
        """
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity

        conn = cur = None
        try:
            conn = mgr.get_connection()
            cur = conn.cursor()

            params: List[str] = []

            # Determine the seed text
            if incident_id:
                cur.execute(
                    "SELECT COALESCE(short_desc,'') || ' ' || COALESCE(description,'') "
                    "FROM itsm.incident WHERE id = %s",
                    [incident_id],
                )
                row = cur.fetchone()
                if not row:
                    raise ValueError(f"Incident {incident_id} not found")
                seed_txt = row[0]
            elif text:
                seed_txt = text
            else:
                raise ValueError("Provide text or incident_id")

            query = (
                "SELECT id, short_desc, description FROM itsm.incident "
                "WHERE opened_at >= NOW() - INTERVAL %s "
                "ORDER BY opened_at DESC LIMIT %s"
            )
            exec_params: List[str | int] = [f"{lookback_days} days", limit]

            if text:
                tokens = re.findall(r"\w+", text)[:5]
                if tokens:
                    params.extend([f"%{t}%" for t in tokens])
                    query = (
                        "SELECT id, COALESCE(short_desc,'') || ' ' || COALESCE(description,'') AS txt "
                        "FROM (" + query + ") AS sub "
                        "WHERE (" + " OR ".join(["short_desc ILIKE %s"] * len(tokens)) + ")"
                    )
                    exec_params = exec_params + params
                else:
                    query = (
                        "SELECT id, COALESCE(short_desc,'') || ' ' || COALESCE(description,'') AS txt "
                        "FROM (" + query + ") AS sub"
                    )
            else:
                query = (
                    "SELECT id, COALESCE(short_desc,'') || ' ' || COALESCE(description,'') AS txt "
                    "FROM (" + query + ") AS sub"
                )

            cur.execute(query, exec_params)
            top: List[tuple[float, str]] = []
            found_seed = False
            while True:
                batch = cur.fetchmany(1000)
                if not batch:
                    break
                ids = [r[0] for r in batch]
                txts = [r[1] for r in batch]
                if len(txts) < 2:
                    continue
                vec = TfidfVectorizer(
                    min_df=1 if len(txts) < 2 else 2,
                    max_features=5000,
                )
                X = vec.fit_transform(txts + [seed_txt])
                sims = cosine_similarity(X[-1], X[:-1]).ravel()
                for i, sim in enumerate(sims):
                    if incident_id and ids[i] == incident_id:
                        found_seed = True
                        continue
                    heapq.heappush(top, (sim, ids[i]))
                    if len(top) > self.top_k:
                        heapq.heappop(top)

            if not top:
                return []
            if incident_id and not found_seed:
                raise ValueError(f"Incident {incident_id} not found")

            top.sort(reverse=True)
            results = [
                {"id": id_, "similarity": float(sim)} for sim, id_ in top
            ]

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
            if cur:
                cur.close()
            if conn:
                mgr.release_connection(conn)
