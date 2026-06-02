AUDIT (
  name audit_wac_block,
  dialect postgres
);
SELECT
  geoid,
  c000
FROM @this
WHERE COALESCE(c000, 0) < 0
