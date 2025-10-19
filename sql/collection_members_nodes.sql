SELECT
    cm.collection_id,
    cm.collection_name,
    cm.collection_type,
    cm.cmdb_id,
    n.node_name,
    n.cluster_name,
    n.location,
    cm.updated_at
FROM {collection_members_nodes} AS cm
LEFT JOIN {nodes_table} AS n ON n.cmdb_id = cm.cmdb_id
WHERE (%s IS NULL OR cm.collection_id = %s)
  AND (%s IS NULL OR cm.collection_type ILIKE %s)
ORDER BY cm.updated_at DESC
LIMIT %s;
