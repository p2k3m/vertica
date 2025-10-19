WITH evt AS (
    SELECT
        e.event_id,
        e.application,
        e.related_ci_display_label AS ci_name,
        e.related_ci_cmdb_id      AS ci_cmdb_id,
        e.related_ci_type         AS ci_type,
        e.time_created
    FROM {events_table} AS e
    WHERE e.lifecycle_state = 'open'
      AND (%s IS NULL OR e.application ILIKE %s)
      AND e.time_created <= %s
    ORDER BY e.time_created DESC
    LIMIT %s
)
SELECT DISTINCT
    evt.ci_name,
    evt.ci_cmdb_id,
    evt.ci_type,
    COALESCE(p.location, n.location, c.location) AS location,
    ARRAY[evt.application, COALESCE(p.cluster_name, n.cluster_name, c.cluster_name), evt.ci_type] AS relationship_path
FROM evt
LEFT JOIN {pods_table} AS p  ON p.cmdb_id = evt.ci_cmdb_id
LEFT JOIN {nodes_table} AS n ON n.cmdb_id = evt.ci_cmdb_id
LEFT JOIN {containers_table} AS c ON c.cmdb_id = evt.ci_cmdb_id;
