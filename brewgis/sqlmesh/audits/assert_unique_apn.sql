AUDIT (
  name assert_unique_apn,
  dialect postgres
);

-- Each row returned is a failure — one per duplicated APN.
SELECT
  apn,
  COUNT(*) AS copies
FROM @this_model
GROUP BY apn
HAVING COUNT(*) > 1
ORDER BY copies DESC
LIMIT 50;
