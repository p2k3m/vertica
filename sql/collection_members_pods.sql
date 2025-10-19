SELECT
    cm.collection_id,
    cm.collection_name,
    cm.collection_type,
    cm.cmdb_id,
    p.pod_name,
    p.cluster_name,
    p.namespace,
    cm.updated_at
FROM {collection_members_pods} AS cm
LEFT JOIN {pods_table} AS p ON p.cmdb_id = cm.cmdb_id
WHERE (%s IS NULL OR cm.collection_id = %s)
  AND (%s IS NULL OR cm.collection_type ILIKE %s)
ORDER BY cm.updated_at DESC
LIMIT %s;
