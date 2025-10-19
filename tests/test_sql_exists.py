from pathlib import Path

import pytest

SQL_FILES = [
    "get_event_application.sql",
    "cis_for_business_service_events.sql",
    "collection_for_ci.sql",
    "collection_members_nodes.sql",
    "collection_members_pods.sql",
    "collection_members_containers.sql",
    "ci_facts_node.sql",
    "ci_facts_pod.sql",
    "ci_facts_container.sql",
    "security_alerts_last7d.sql",
    "search_tables.sql",
    "search_columns.sql",
    "list_views.sql",
    "list_indexes.sql",
    "get_event_ci.sql",
]


@pytest.mark.parametrize("filename", SQL_FILES)
def test_sql_file_exists(filename: str) -> None:
    path = Path("sql") / filename
    assert path.is_file(), f"Missing SQL template {filename}"
    content = path.read_text(encoding="utf-8").strip()
    assert content, f"SQL template {filename} is empty"
