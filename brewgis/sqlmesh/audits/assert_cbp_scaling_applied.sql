AUDIT (
  name assert_cbp_scaling_applied,
  dialect postgres
);
WITH actual AS (
  SELECT
    COALESCE(SUM(emp_manufacturing + emp_wholesale + emp_transport_warehousing + emp_utilities + emp_construction), 0) AS actual_emp_ind_total,
    COALESCE(SUM(emp_retail_services + emp_restaurant + emp_accommodation + emp_arts_entertainment + emp_other_services), 0) AS actual_emp_ret_total,
    COALESCE(SUM(emp_office_services + emp_medical_services), 0) AS actual_emp_off_total
  FROM @this_model
),
raw_total AS (
  SELECT
    COALESCE(SUM(emp_manufacturing + emp_wholesale + emp_transport_warehousing + emp_utilities + emp_construction), 0) AS raw_ind_total,
    COALESCE(SUM(emp_retail_services + emp_restaurant + emp_accommodation + emp_arts_entertainment + emp_other_services), 0) AS raw_ret_total,
    COALESCE(SUM(emp_office_services + emp_medical_services), 0) AS raw_off_total
  FROM brewgis.staging.wac_block_raw
)
SELECT
  a.actual_emp_ind_total,
  a.actual_emp_ret_total,
  a.actual_emp_off_total,
  r.raw_ind_total,
  r.raw_ret_total,
  r.raw_off_total
FROM actual a, raw_total r
WHERE
  (
    0 = 0 AND 0 = 0 AND 0 = 0
    AND (
      a.actual_emp_ind_total < r.raw_ind_total * 0.99
      OR a.actual_emp_ind_total > r.raw_ind_total * 1.01
      OR a.actual_emp_ret_total < r.raw_ret_total * 0.99
      OR a.actual_emp_ret_total > r.raw_ret_total * 1.01
      OR a.actual_emp_off_total < r.raw_off_total * 0.99
      OR a.actual_emp_off_total > r.raw_off_total * 1.01
    )
  )
