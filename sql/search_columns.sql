SELECT
    table_schema,
    table_name,
    column_name,
    data_type
FROM v_catalog.columns
WHERE (%s IS NULL OR table_schema ILIKE %s)
  AND (%s IS NULL OR table_name ILIKE %s)
  AND (%s IS NULL OR column_name ILIKE %s)
ORDER BY table_schema, table_name, ordinal_position
LIMIT %s;
