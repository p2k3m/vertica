SELECT
    e.event_id,
    e.application,
    e.related_ci_display_label AS ci_name,
    e.related_ci_cmdb_id      AS ci_cmdb_id,
    e.related_ci_type         AS ci_type,
    e.time_created
FROM {events_table} AS e
WHERE e.event_id = %s
LIMIT 1;
