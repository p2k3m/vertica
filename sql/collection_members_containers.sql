SELECT
    cm.collection_id,
    cm.collection_name,
    cm.collection_type,
    cm.cmdb_id,
    c.container_name,
    c.cluster_name,
    c.namespace,
    cm.updated_at
FROM {collection_members_containers} AS cm
LEFT JOIN {containers_table} AS c ON c.cmdb_id = cm.cmdb_id
WHERE (%s IS NULL OR cm.collection_id = %s)
  AND (%s IS NULL OR cm.collection_type ILIKE %s)
ORDER BY cm.updated_at DESC
LIMIT %s;
