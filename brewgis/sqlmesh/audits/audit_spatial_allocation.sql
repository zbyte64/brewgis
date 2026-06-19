AUDIT (
  name audit_spatial_allocation,
  dialect postgres
);
SELECT
  parcel_id,
  emp,
  emp_ret,
  emp_off,
  emp_pub,
  emp_ind,
  emp_ag
FROM @this_model
WHERE COALESCE(emp, 0) < 0
   OR COALESCE(emp_ret, 0) < 0
   OR COALESCE(emp_off, 0) < 0
   OR COALESCE(emp_pub, 0) < 0
   OR COALESCE(emp_ind, 0) < 0
   OR COALESCE(emp_ag, 0) < 0
