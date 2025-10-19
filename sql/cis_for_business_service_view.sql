-- Use when bs_id and a clean BS→CI view exists
SELECT ci_id, ci_name, ci_type, location, rel_path
FROM {view_bs_to_ci}
WHERE bs_id = %s;
