AUDIT (
  name audit_base_canvas,
  dialect postgres
);
SELECT *
FROM @this_model
WHERE (SELECT COUNT(*) FROM @this) = 0
   OR geometry IS NULL
   LIMIT 1
