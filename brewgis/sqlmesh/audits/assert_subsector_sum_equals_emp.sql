AUDIT (
  name assert_subsector_sum_equals_emp,
  dialect postgres
);
SELECT
  parcel_id,
  emp,
  COALESCE(emp_retail_services, 0)
    + COALESCE(emp_restaurant, 0)
    + COALESCE(emp_accommodation, 0)
    + COALESCE(emp_arts_entertainment, 0)
    + COALESCE(emp_other_services, 0)
    + COALESCE(emp_office_services, 0)
    + COALESCE(emp_medical_services, 0)
    + COALESCE(emp_public_admin, 0)
    + COALESCE(emp_education, 0)
    + COALESCE(emp_manufacturing, 0)
    + COALESCE(emp_wholesale, 0)
    + COALESCE(emp_transport_warehousing, 0)
    + COALESCE(emp_utilities, 0)
    + COALESCE(emp_construction, 0)
    + COALESCE(emp_agriculture, 0)
    + COALESCE(emp_extraction, 0)
    + COALESCE(emp_military, 0) AS subsector_sum
FROM @this_model
WHERE ABS(
  emp - (
    COALESCE(emp_retail_services, 0)
    + COALESCE(emp_restaurant, 0)
    + COALESCE(emp_accommodation, 0)
    + COALESCE(emp_arts_entertainment, 0)
    + COALESCE(emp_other_services, 0)
    + COALESCE(emp_office_services, 0)
    + COALESCE(emp_medical_services, 0)
    + COALESCE(emp_public_admin, 0)
    + COALESCE(emp_education, 0)
    + COALESCE(emp_manufacturing, 0)
    + COALESCE(emp_wholesale, 0)
    + COALESCE(emp_transport_warehousing, 0)
    + COALESCE(emp_utilities, 0)
    + COALESCE(emp_construction, 0)
    + COALESCE(emp_agriculture, 0)
    + COALESCE(emp_extraction, 0)
    + COALESCE(emp_military, 0)
  )
) > 0.5
