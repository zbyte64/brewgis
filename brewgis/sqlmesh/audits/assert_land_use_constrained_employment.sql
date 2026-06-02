AUDIT (
  name assert_land_use_constrained_employment,
  dialect postgres
);
SELECT
  parcel_id,
  land_development_category,
  emp,
  COALESCE(emp_manufacturing, 0) + COALESCE(emp_wholesale, 0)
    + COALESCE(emp_transport_warehousing, 0) + COALESCE(emp_utilities, 0)
    + COALESCE(emp_construction, 0) AS emp_ind,
  COALESCE(emp_agriculture, 0) AS emp_agriculture
FROM @this
WHERE (
  land_development_category IS NOT NULL
  AND land_development_category NOT IN ('industrial')
  AND COALESCE(emp_manufacturing, 0) + COALESCE(emp_wholesale, 0)
    + COALESCE(emp_transport_warehousing, 0) + COALESCE(emp_utilities, 0)
    + COALESCE(emp_construction, 0) > 0
) OR (
  land_development_category IS NOT NULL
  AND land_development_category NOT IN ('agricultural', 'industrial')
  AND COALESCE(emp_agriculture, 0) > 0
) OR (
  land_development_category = 'undeveloped'
  AND COALESCE(emp, 0) > 0
)
