import requests, json, re
from dataclasses import dataclass
from typing import Dict, List, Any, Optional
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

    def _schema_snapshot(self, mgr: VerticaConnectionManager) -> str:
        conn = cur = None
        try:
            conn = mgr.get_connection()
            cur = conn.cursor()
            cur.execute("""
                SELECT table_schema, table_name, column_name, data_type
                FROM v_catalog.columns
                WHERE table_schema IN ('itsm','cmdb','public','store','VMart')
                ORDER BY table_schema, table_name, ordinal_position
            """)
            rows = cur.fetchall()
            lines = []
            for s, t, c, dt in rows:
                lines.append(f"{s}.{t}.{c} {dt}")
            return "\n".join(lines[:800])  # cap to keep prompt small
        finally:
            if cur: cur.close()
            if conn: mgr.release_connection(conn)

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
        r = requests.post(f"{self.ollama_host}/api/generate", json=payload, timeout=120)
        r.raise_for_status()
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
            if incident_id:
                cur.execute("SELECT id, COALESCE(short_desc,'') || ' ' || COALESCE(description,'') AS txt FROM itsm.incident")
                rows = cur.fetchall()
                corpus_ids = [r[0] for r in rows]
                corpus_txt = [r[1] for r in rows]
                if incident_id not in corpus_ids:
                    raise ValueError(f"Incident {incident_id} not found")
                seed_txt = corpus_txt[corpus_ids.index(incident_id)]
            else:
                if not text:
                    raise ValueError("Provide text or incident_id")
                cur.execute("SELECT id, COALESCE(short_desc,'') || ' ' || COALESCE(description,'') AS txt FROM itsm.incident")
                rows = cur.fetchall()
                corpus_ids = [r[0] for r in rows]
                corpus_txt = [r[1] for r in rows]
                seed_txt = text
            vec = TfidfVectorizer(min_df=2, max_features=5000)
            X = vec.fit_transform(corpus_txt)
            from scipy.sparse import vstack
            import numpy as np
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
            by_id = {r[0]: {"id": r[0], "status": r[1], "closed_at": r[2], "assignment_group": r[3], "short_desc": r[4]} for r in recs}
            for r in results:
                r.update(by_id.get(r["id"], {}))
            return results
        finally:
            if cur: cur.close()
            if conn: mgr.release_connection(conn)
