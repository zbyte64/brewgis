-- Verify that with employment_land_use_constrain=true:
--   emp_ind > 0 only on 'industrial' parcels (NULL is unconstrained → allowed)
--   emp_agriculture > 0 only on 'agricultural' or 'industrial' parcels (NULL is unconstrained → allowed)
--   emp > 0 only on non-'undeveloped' parcels (NULL is unconstrained → allowed)
--
-- With NLCD-based classification active, parcels should have non-null
-- land_development_category values, making the constraints effective.

SELECT
    parcel_id,
    land_development_category,
    emp,
    emp_manufacturing + emp_wholesale + emp_transport_warehousing + emp_utilities + emp_construction AS emp_ind,
    emp_agriculture
FROM {{ ref('base_canvas_employment') }}
WHERE (
    -- Industrial employment on non-industrial, non-NULL parcels
    land_development_category IS NOT NULL
    AND land_development_category NOT IN ('industrial')
    AND COALESCE(emp_manufacturing, 0) + COALESCE(emp_wholesale, 0)
        + COALESCE(emp_transport_warehousing, 0) + COALESCE(emp_utilities, 0)
        + COALESCE(emp_construction, 0) > 0
) OR (
    -- Agricultural employment on non-agricultural, non-industrial, non-NULL parcels
    land_development_category IS NOT NULL
    AND land_development_category NOT IN ('agricultural', 'industrial')
    AND COALESCE(emp_agriculture, 0) > 0
) OR (
    -- Any employment on undeveloped parcels
    land_development_category = 'undeveloped'
    AND COALESCE(emp, 0) > 0
)
