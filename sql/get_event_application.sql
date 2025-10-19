SELECT DISTINCT application
FROM {events_table}
WHERE application IS NOT NULL
  AND NULLIF(TRIM(application), '') IS NOT NULL
ORDER BY application
LIMIT %s;
