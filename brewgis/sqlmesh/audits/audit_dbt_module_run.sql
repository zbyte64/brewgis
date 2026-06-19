AUDIT (
  name audit_dbt_module_run,
  dialect postgres
);
SELECT *
FROM @this_model
WHERE (SELECT COUNT(*) FROM @this) = 0
   OR (SELECT COUNT(*) FROM @this WHERE pk IS NULL) > 0
   OR (SELECT COUNT(*) FROM @this WHERE geography_id IS NULL) > 0
   LIMIT 1
