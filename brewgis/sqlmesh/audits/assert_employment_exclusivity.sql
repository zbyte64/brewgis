AUDIT (
  name assert_employment_exclusivity,
  dialect postgres
);
-- emp_pub never co-located with emp_ret or emp_ind (SACOG source: 0 of 502,874 parcels);
-- emp_military never co-located with any other employment (declared exclusive).
SELECT
  parcel_id,
  emp_pub,
  emp_ret,
  emp_ind,
  emp_military
FROM @this_model
WHERE (COALESCE(emp_pub, 0) > 0
        AND (COALESCE(emp_ret, 0) > 0 OR COALESCE(emp_ind, 0) > 0))
   OR (COALESCE(emp_military, 0) > 0
        AND (COALESCE(emp_ret, 0) + COALESCE(emp_off, 0) + COALESCE(emp_pub, 0)
             + COALESCE(emp_ind, 0) + COALESCE(emp_ag, 0)) > 0);
