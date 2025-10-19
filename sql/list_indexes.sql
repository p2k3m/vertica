SELECT
    projection_schema,
    projection_name,
    anchor_table_name,
    is_super_projection
FROM v_catalog.projections
WHERE (%s IS NULL OR projection_schema ILIKE %s)
  AND (%s IS NULL OR anchor_table_name ILIKE %s)
ORDER BY projection_schema, projection_name
LIMIT %s;
