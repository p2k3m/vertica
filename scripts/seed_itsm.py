import random, string, datetime as dt
from io import StringIO
from mcp_vertica.connection import VerticaConnectionManager, VerticaConfig

CI_CLASSES = ["APP", "DB", "VM", "NETWORK", "STORAGE"]
ENV = ["PROD", "PREPROD", "QA", "DEV"]
PRIO = ["P1","P2","P3","P4"]
STATUS = ["OPEN","ASSIGNED","IN_PROGRESS","RESOLVED","CLOSED"]
REL = ["DEPENDS_ON","RUNS_ON","HOSTED_ON"]
CATS = ["Database","Network","Application","Security","Storage","OS"]

def to_csv_lines(rows):
    for row in rows:
        yield ",".join("" if v is None else str(v) for v in row) + "\n"


def to_csv_buffer(rows):
    return StringIO("".join(to_csv_lines(rows)))

def _rand_id(prefix="INC", n=6):
    return f"{prefix}{''.join(random.choices(string.digits, k=n))}"

def ensure_schema_and_tables(mgr: VerticaConnectionManager):
    with open("sql/itsm_schema.sql", "r", encoding="utf-8") as f:
        ddl = f.read()
    conn = cur = None
    try:
        conn = mgr.get_connection()
        cur = conn.cursor()
        for stmt in [s.strip() for s in ddl.split(";") if s.strip()]:
            cur.execute(stmt + ";")
        conn.commit()
    finally:
        if cur: cur.close()
        if conn: mgr.release_connection(conn)

def synthesize_and_load(mgr: VerticaConnectionManager, n_incidents: int = 2000):
    # synthesize CI / CI relations / changes / incidents
    conn = cur = None
    try:
        conn = mgr.get_connection()
        cur = conn.cursor()
        # CIS
        cis = []
        for i in range(200):
            cid = _rand_id("CI", 6)
            cis.append((cid, f"ci-{i}", random.choice(CI_CLASSES), random.choice(ENV), "owner@example.com", random.choice(["LOW","MEDIUM","HIGH"])))
        cur.copy(
            "COPY cmdb.ci (id,name,class,environment,owner,criticality) FROM STDIN DELIMITER ','",
            to_csv_buffer(cis),
        )
        # CI relations
        def gen_rels():
            for _ in range(400):
                p = random.choice(cis)[0]
                c = random.choice(cis)[0]
                if p != c:
                    yield (p, random.choice(REL), c)
        cur.copy(
            "COPY cmdb.ci_rel (parent_ci,relation,child_ci) FROM STDIN DELIMITER ','",
            to_csv_buffer(gen_rels()),
        )
        # Changes
        base = dt.datetime.now() - dt.timedelta(days=90)
        def gen_changes():
            for i in range(500):
                chid = _rand_id("CHG", 6)
                wstart = base + dt.timedelta(days=random.randint(0, 60))
                wend = wstart + dt.timedelta(hours=random.choice([1,2,4]))
                yield (chid, base, wstart, wend, random.choice(["LOW","MEDIUM","HIGH"]), random.choice(["SCHEDULED","IMPLEMENTED","FAILED"]), f"Change {i}", random.choice(cis)[0])
        cur.copy(
            "COPY itsm.change (id, requested_at, window_start, window_end, risk, status, description, ci_id) FROM STDIN DELIMITER ','",
            to_csv_buffer(gen_changes()),
        )
        # Incidents
        def gen_incidents():
            for i in range(n_incidents):
                iid = _rand_id("INC", 6)
                opened = base + dt.timedelta(days=random.randint(0, 60))
                closed = opened + dt.timedelta(hours=random.randint(1,72)) if random.random() > 0.3 else None
                txt = random.choice([
                    "DB connection timeout on payment service",
                    "High CPU on VM during backup window",
                    "Network packet loss between AZs",
                    "App 500 errors after deploy",
                    "Slow query on orders table",
                    "Disk latency spike on storage node",
                    "SSL cert mismatch on gateway",
                    "Pods evicted due to memory pressure"
                ])
                yield (iid, opened, random.choice(PRIO), random.choice(CATS), random.choice(["DBA","NETOPS","APPENG","SECOPS"]), txt[:80], txt, random.choice(STATUS), closed, random.choice(cis)[0])
        cur.copy(
            "COPY itsm.incident (id, opened_at, priority, category, assignment_group, short_desc, description, status, closed_at, ci_id) FROM STDIN DELIMITER ','",
            to_csv_buffer(gen_incidents()),
        )
        conn.commit()
    finally:
        if cur: cur.close()
        if conn: mgr.release_connection(conn)

def main():
    cfg = VerticaConfig.from_env()
    mgr = VerticaConnectionManager()
    mgr.initialize_default(cfg)
    ensure_schema_and_tables(mgr)
    synthesize_and_load(mgr, 2000)
    print("Seed complete.")

if __name__ == "__main__":
    main()
