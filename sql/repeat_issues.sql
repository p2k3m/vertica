WITH cluster AS (
  SELECT cluster_name FROM (
    SELECT cluster_name, timestamp_utc_end_s FROM {schema}.cloud_gcp_gke_pod  WHERE cmdb_id=%s
    UNION ALL SELECT cluster_name, timestamp_utc_end_s FROM {schema}.cloud_gcp_gke_node WHERE cmdb_id=%s
    UNION ALL SELECT cluster_name, timestamp_utc_end_s FROM {schema}.cloud_gcp_gke_container WHERE cmdb_id=%s
  ) u ORDER BY timestamp_utc_end_s DESC LIMIT 1
), cand AS (
  SELECT event_id, title, description, related_ci_cmdb_id, duplicate_count, time_created, application,
         related_ci_display_label AS ci_name
  FROM {schema}.opr_event
  WHERE time_created BETWEEN %s AND %s
    AND /* token filter */ %s
), scored AS (
  SELECT c.*,
         (CASE WHEN (SELECT cluster_name FROM cluster) IS NOT NULL AND EXISTS (
           SELECT 1 FROM {schema}.opr_event e
           JOIN {schema}.cloud_gcp_gke_pod p ON p.cmdb_id = e.related_ci_cmdb_id AND p.cluster_name = (SELECT cluster_name FROM cluster)
           WHERE e.event_id = c.event_id
         ) THEN 1 ELSE 0 END) AS same_cluster,
         EXTRACT(EPOCH FROM (%s::timestamp - c.time_created::timestamp)) / 3600.0 AS age_hours
  FROM cand c
)
SELECT event_id, ci_name, related_ci_cmdb_id, application, duplicate_count, time_created,
       (CASE WHEN same_cluster=1 THEN 1 ELSE 0 END) AS cluster_match,
       (GREATEST(0, 72 - age_hours)) + (duplicate_count * 5) + (CASE WHEN same_cluster=1 THEN 20 ELSE 0 END) AS rank_score
FROM scored
ORDER BY rank_score DESC
LIMIT %s;
