AUDIT (
  name assert_cns18_20_mapped,
  dialect postgres
);
WITH lodes_sum AS (
  SELECT
    SUM(cns01 + cns02 + cns03 + cns04 + cns05 + cns06 + cns07
      + cns08 + cns09 + cns10 + cns11 + cns12 + cns13 + cns14
      + cns15 + cns16 + cns17 + cns18 + cns19 + cns20) AS lodes_all_cns
  FROM public.lodes_raw
  WHERE year = 2008
    AND LEFT(w_geocode, 5) = '06067'
),
actual AS (
  SELECT
    SUM(COALESCE(emp_agriculture, 0) + COALESCE(emp_extraction, 0)
      + COALESCE(emp_construction, 0) + COALESCE(emp_manufacturing, 0)
      + COALESCE(emp_transport_warehousing, 0) + COALESCE(emp_utilities, 0)
      + COALESCE(emp_wholesale, 0) + COALESCE(emp_retail_services, 0)
      + COALESCE(emp_office_services, 0) + COALESCE(emp_education, 0)
      + COALESCE(emp_medical_services, 0) + COALESCE(emp_arts_entertainment, 0)
      + COALESCE(emp_accommodation, 0) + COALESCE(emp_restaurant, 0)
      + COALESCE(emp_other_services, 0) + COALESCE(emp_public_admin, 0)
      + COALESCE(emp_military, 0)) AS actual_total
  FROM @this
)
SELECT
  a.actual_total,
  l.lodes_all_cns,
  ABS(a.actual_total - l.lodes_all_cns) AS abs_diff
FROM actual a, lodes_sum l
WHERE l.lodes_all_cns > 0
  AND ABS(a.actual_total - l.lodes_all_cns) / l.lodes_all_cns > 0.01
