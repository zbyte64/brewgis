AUDIT (
  name audit_built_form_export,
  dialect postgres
);
SELECT
  id,
  built_form_key
FROM @this
WHERE built_form_key IS NULL
