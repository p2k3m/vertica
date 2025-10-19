SELECT
    alert_id,
    alert_type,
    severity,
    resource_id,
    message,
    created_at
FROM {security_alerts_table}
WHERE created_at >= (CURRENT_TIMESTAMP - INTERVAL '7 days')
ORDER BY created_at DESC
LIMIT %s;
