AUDIT (
  name assert_industrial_sectors_use_industrial_sqft,
  dialect postgres
);
-- Only parcels with industrial sqft>0 get industrial sector jobs
SELECT
  parcel_id,
  industrial_building_sqft,
  emp_manufacturing,
  emp_wholesale,
  emp_transport_warehousing,
  emp_utilities,
  emp_construction
FROM @this_model
WHERE COALESCE(industrial_building_sqft, 0) <= 0
  AND (
    COALESCE(emp_manufacturing, 0) > 0
    OR COALESCE(emp_wholesale, 0) > 0
    OR COALESCE(emp_transport_warehousing, 0) > 0
    OR COALESCE(emp_utilities, 0) > 0
    OR COALESCE(emp_construction, 0) > 0
  );
