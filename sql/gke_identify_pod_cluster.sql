SELECT cluster_name, project_id, location
FROM {schema}.cloud_gcp_gke_pod
WHERE cmdb_id = %s
ORDER BY timestamp_utc_end_s DESC
LIMIT 1;
