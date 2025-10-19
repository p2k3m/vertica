SELECT
    table_schema,
    table_name,
    row_count,
    create_time
FROM v_catalog.tables
WHERE (%s IS NULL OR table_schema ILIKE %s)
  AND (%s IS NULL OR table_name ILIKE %s)
ORDER BY create_time DESC
LIMIT %s;
