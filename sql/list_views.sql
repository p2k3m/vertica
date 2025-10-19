SELECT
    table_schema,
    table_name,
    view_definition
FROM v_catalog.views
WHERE (%s IS NULL OR table_schema ILIKE %s)
ORDER BY table_schema, table_name
LIMIT %s;
