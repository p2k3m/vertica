SELECT
    n.cmdb_id,
    n.node_name,
    n.cluster_name,
    n.location,
    n.owner_team,
    n.last_seen_at
FROM {nodes_table} AS n
WHERE (%s IS NULL OR n.cmdb_id = %s)
  AND (%s IS NULL OR n.node_name ILIKE %s)
ORDER BY n.last_seen_at DESC
LIMIT %s;
