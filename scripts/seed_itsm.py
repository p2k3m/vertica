import random, string, datetime as dt
from pathlib import Path

import csv
import io
import sqlparse
from mcp_vertica.connection import VerticaConnectionManager, VerticaConfig

CI_CLASSES = ["APP", "DB", "VM", "NETWORK", "STORAGE"]
ENV = ["PROD", "PREPROD", "QA", "DEV"]
PRIO = ["P1", "P2", "P3", "P4"]
STATUS = ["OPEN", "ASSIGNED", "IN_PROGRESS", "RESOLVED", "CLOSED"]
REL = ["DEPENDS_ON", "RUNS_ON", "HOSTED_ON"]
CATS = ["Database", "Network", "Application", "Security", "Storage", "OS"]

def rows_to_buffer(write_rows):
    buf = io.StringIO()
    # Quote all fields so COPY ... ENCLOSED BY '"' works regardless of content
    writer = csv.writer(buf, lineterminator="\n", quoting=csv.QUOTE_ALL)

    def write_row(row):
        writer.writerow(["\\N" if v is None else v for v in row])

    write_rows(write_row)
    buf.seek(0)
    return buf

def _rand_id(prefix="INC", n=6):
    return f"{prefix}{''.join(random.choices(string.digits, k=n))}"

def ensure_schema_and_tables(mgr: VerticaConnectionManager):
    schema_path = Path(__file__).parent.parent / "sql" / "itsm_schema.sql"
    with open(schema_path, "r", encoding="utf-8") as f:
        ddl = f.read()
    conn = cur = None
    try:
        conn = mgr.get_connection()
        conn.autocommit = False  # disable autocommit for explicit transaction control
        cur = conn.cursor()
        try:
            for stmt in [s.strip() for s in sqlparse.split(ddl) if s.strip()]:
                cur.execute(stmt)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    finally:
        if cur:
            cur.close()
        if conn:
            mgr.release_connection(conn)

def synthesize_and_load(mgr: VerticaConnectionManager, n_incidents: int = 2000):
    # synthesize CI / CI relations / changes / incidents
    conn = cur = None
    try:
        conn = mgr.get_connection()
        conn.autocommit = False  # disable autocommit for explicit transaction control
        cur = conn.cursor()
        cis: list[tuple] = []
        ci_ids = set()

        def write_cis(write_row):
            for i in range(200):
                cid = _rand_id("CI", 6)
                while cid in ci_ids:
                    cid = _rand_id("CI", 6)
                ci_ids.add(cid)
                row = (
                    cid,
                    f"ci-{i}",
                    random.choice(CI_CLASSES),
                    random.choice(ENV),
                    "owner@example.com",
                    random.choice(["LOW", "MEDIUM", "HIGH"]),
                )
                cis.append(row)
                write_row(row)

        buf = rows_to_buffer(write_cis)
        cur.copy(
            "COPY cmdb.ci (id,name,class,environment,owner,criticality) FROM STDIN DELIMITER ',' ENCLOSED BY '\"' NULL '\\N'",
            buf,
        )

        def write_rels(write_row):
            for _ in range(400):
                p = random.choice(cis)[0]
                c = random.choice(cis)[0]
                if p != c:
                    write_row((p, random.choice(REL), c))

        buf = rows_to_buffer(write_rels)
        cur.copy(
            "COPY cmdb.ci_rel (parent_ci,relation,child_ci) FROM STDIN DELIMITER ',' ENCLOSED BY '\"' NULL '\\N'",
            buf,
        )

        base = dt.datetime.now() - dt.timedelta(days=90)
        change_ids = set()

        def write_changes(write_row):
            for i in range(500):
                chid = _rand_id("CHG", 6)
                while chid in change_ids:
                    chid = _rand_id("CHG", 6)
                change_ids.add(chid)
                requested_at = base + dt.timedelta(days=random.randint(0, 60))
                wstart = base + dt.timedelta(days=random.randint(0, 60))
                wend = wstart + dt.timedelta(hours=random.choice([1, 2, 4]))
                write_row(
                    (
                        chid,
                        requested_at,
                        wstart,
                        wend,
                        random.choice(["LOW", "MEDIUM", "HIGH"]),
                        random.choice(["SCHEDULED", "IMPLEMENTED", "FAILED"]),
                        f"Change {i}",
                        random.choice(cis)[0],
                    )
                )

        buf = rows_to_buffer(write_changes)
        cur.copy(
            "COPY itsm.change (id, requested_at, window_start, window_end, risk, status, description, ci_id) FROM STDIN DELIMITER ',' ENCLOSED BY '\"' NULL '\\N'",
            buf,
        )

        incident_ids = set()

        def write_incidents(write_row):
            for i in range(n_incidents):
                iid = _rand_id("INC", 6)
                while iid in incident_ids:
                    iid = _rand_id("INC", 6)
                incident_ids.add(iid)
                opened = base + dt.timedelta(days=random.randint(0, 60))
                closed = (
                    opened + dt.timedelta(hours=random.randint(1, 72))
                    if random.random() > 0.3
                    else None
                )
                txt = random.choice(
                    [
                        "DB connection timeout on payment service",
                        "High CPU on VM during backup window",
                        "Network packet loss between AZs",
                        "App 500 errors after deploy",
                        "Slow query on orders table",
                        "Disk latency spike on storage node",
                        "SSL cert mismatch on gateway",
                        "Pods evicted due to memory pressure",
                    ]
                )
                write_row(
                    (
                        iid,
                        opened,
                        random.choice(PRIO),
                        random.choice(CATS),
                        random.choice(["DBA", "NETOPS", "APPENG", "SECOPS"]),
                        txt[:80],
                        txt,
                        random.choice(STATUS),
                        closed,
                        random.choice(cis)[0],
                    )
                )

        buf = rows_to_buffer(write_incidents)
        cur.copy(
            "COPY itsm.incident (id, opened_at, priority, category, assignment_group, short_desc, description, status, closed_at, ci_id) FROM STDIN DELIMITER ',' ENCLOSED BY '\"' NULL '\\N'",
            buf,
        )

        conn.commit()
    except Exception:
        if conn:
            conn.rollback()
        raise
    finally:
        if cur:
            cur.close()
        if conn:
            mgr.release_connection(conn)

def main():
    cfg = VerticaConfig.from_env()
    mgr = VerticaConnectionManager()
    mgr.initialize_default(cfg)
    try:
        ensure_schema_and_tables(mgr)
        synthesize_and_load(mgr, 2000)
        print("Seed complete.")
    finally:
        mgr.close_all()  # release pooled connections

if __name__ == "__main__":
    main()
