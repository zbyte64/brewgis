AUDIT (
  name assert_du_assessor_units_direct,
  dialect postgres
);
-- assessor.units>0 → du = assessor.units
SELECT
  apn,
  assessor_units,
  du
FROM @this_model
WHERE COALESCE(assessor_units, 0) > 0
  AND ABS(du - assessor_units) > 0.01;
