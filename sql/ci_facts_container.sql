SELECT
    c.cmdb_id,
    c.container_name,
    c.cluster_name,
    c.namespace,
    c.image,
    c.last_seen_at
FROM {containers_table} AS c
WHERE (%s IS NULL OR c.cmdb_id = %s)
  AND (%s IS NULL OR c.container_name ILIKE %s)
ORDER BY c.last_seen_at DESC
LIMIT %s;
