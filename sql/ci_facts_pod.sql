SELECT
    p.cmdb_id,
    p.pod_name,
    p.cluster_name,
    p.namespace,
    p.owner_team,
    p.last_seen_at
FROM {pods_table} AS p
WHERE (%s IS NULL OR p.cmdb_id = %s)
  AND (%s IS NULL OR p.pod_name ILIKE %s)
ORDER BY p.last_seen_at DESC
LIMIT %s;
