from pathlib import Path
import re

SQL_DIR = Path(__file__).resolve().parents[1] / "sql"

REQUIRED = [
  'get_event_application.sql',
  'cis_for_business_service_view.sql',
  'cis_for_business_service_events.sql',
  'collection_for_ci.sql',
  'collection_members_nodes.sql',
  'collection_members_pods.sql',
  'collection_members_containers.sql',
  'ci_facts_node.sql','ci_facts_pod.sql','ci_facts_container.sql','ci_facts_security_7d.sql',
  'get_event_ci.sql','gke_identify_application_pod.sql','gke_identify_pod_cluster.sql','gke_identify_pod_node.sql',
  'repeat_issues.sql']

def test_required_sql_present():
    missing = [f for f in REQUIRED if not (SQL_DIR / f).exists()]
    assert not missing, f"Missing SQL: {missing}"

PARAM_RE = re.compile(r"%s")

def test_only_positional_params():
    for path in SQL_DIR.glob('*.sql'):
        txt = path.read_text()
        assert PARAM_RE.search(txt) or '{' in txt
