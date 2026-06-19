AUDIT (
  name assert_commercial_sectors_use_commercial_sqft,
  dialect postgres
);
-- Only parcels with commercial sqft>0 get commercial sector jobs
SELECT
  parcel_id,
  commercial_building_sqft,
  emp_retail_services,
  emp_restaurant,
  emp_accommodation,
  emp_arts_entertainment,
  emp_other_services,
  emp_office_services,
  emp_medical_services
FROM @this_model
WHERE COALESCE(commercial_building_sqft, 0) <= 0
  AND (
    COALESCE(emp_retail_services, 0) > 0
    OR COALESCE(emp_restaurant, 0) > 0
    OR COALESCE(emp_accommodation, 0) > 0
    OR COALESCE(emp_arts_entertainment, 0) > 0
    OR COALESCE(emp_other_services, 0) > 0
    OR COALESCE(emp_office_services, 0) > 0
    OR COALESCE(emp_medical_services, 0) > 0
  );
