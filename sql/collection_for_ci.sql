WITH hits AS (
  SELECT 'gke_pod' AS source, cmdb_id, cluster_name, location, project_id, pod_name AS name, timestamp_utc_end_s
  FROM {schema}.cloud_gcp_gke_pod
  WHERE (%s IS NOT NULL AND cmdb_id = %s)
     OR (%s IS NOT NULL AND (pod_name ILIKE %s OR resource_name ILIKE %s))
  UNION ALL
  SELECT 'gke_node', cmdb_id, cluster_name, location, project_id, resource_name, timestamp_utc_end_s
  FROM {schema}.cloud_gcp_gke_node
  WHERE (%s IS NOT NULL AND cmdb_id = %s)
     OR (%s IS NOT NULL AND (resource_name ILIKE %s))
  UNION ALL
  SELECT 'gke_container', cmdb_id, cluster_name, location, project_id, resource_name, timestamp_utc_end_s
  FROM {schema}.cloud_gcp_gke_container
  WHERE (%s IS NOT NULL AND cmdb_id = %s)
     OR (%s IS NOT NULL AND (resource_name ILIKE %s OR pod_name ILIKE %s))
), ranked AS (
  SELECT *, ROW_NUMBER() OVER (ORDER BY timestamp_utc_end_s DESC) AS rn FROM hits
)
SELECT source AS collection_type, cluster_name AS collection_id, location, project_id, name AS matched_name
FROM ranked WHERE rn = 1;
