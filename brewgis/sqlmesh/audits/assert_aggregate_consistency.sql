AUDIT (
  name assert_aggregate_consistency,
  dialect postgres
);
SELECT
  parcel_id,
  emp_ret,
  COALESCE(emp_retail_services, 0) + COALESCE(emp_restaurant, 0)
    + COALESCE(emp_accommodation, 0) + COALESCE(emp_arts_entertainment, 0)
    + COALESCE(emp_other_services, 0) AS emp_ret_sum,
  emp_off,
  COALESCE(emp_office_services, 0) + COALESCE(emp_medical_services, 0) AS emp_off_sum,
  emp_pub,
  COALESCE(emp_public_admin, 0) + COALESCE(emp_education, 0) AS emp_pub_sum,
  emp_ind,
  COALESCE(emp_manufacturing, 0) + COALESCE(emp_wholesale, 0)
    + COALESCE(emp_transport_warehousing, 0) + COALESCE(emp_utilities, 0)
    + COALESCE(emp_construction, 0) + COALESCE(emp_agriculture, 0)
    + COALESCE(emp_extraction, 0) AS emp_ind_sum,
  emp_ag,
  COALESCE(emp_agriculture, 0) AS emp_ag_sum
FROM @this
WHERE
  ABS(emp_ret - (COALESCE(emp_retail_services, 0) + COALESCE(emp_restaurant, 0)
    + COALESCE(emp_accommodation, 0) + COALESCE(emp_arts_entertainment, 0)
    + COALESCE(emp_other_services, 0))) > 0.5
  OR ABS(emp_off - (COALESCE(emp_office_services, 0) + COALESCE(emp_medical_services, 0))) > 0.5
  OR ABS(emp_pub - (COALESCE(emp_public_admin, 0) + COALESCE(emp_education, 0))) > 0.5
  OR ABS(emp_ind - (COALESCE(emp_manufacturing, 0) + COALESCE(emp_wholesale, 0)
    + COALESCE(emp_transport_warehousing, 0) + COALESCE(emp_utilities, 0)
    + COALESCE(emp_construction, 0) + COALESCE(emp_agriculture, 0)
    + COALESCE(emp_extraction, 0))) > 0.5
  OR ABS(emp_ag - COALESCE(emp_agriculture, 0)) > 0.5
