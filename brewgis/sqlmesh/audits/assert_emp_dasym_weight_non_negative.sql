AUDIT (
  name assert_emp_dasym_weight_non_negative,
  dialect postgres
);
-- Employment weight must be non-negative
SELECT
  apn,
  emp_dasym_weight
FROM @this_model
WHERE emp_dasym_weight < 0;
