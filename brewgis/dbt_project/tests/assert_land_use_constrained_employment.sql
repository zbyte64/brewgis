-- Verify that with employment_land_use_constrain=true:
--   emp_ind > 0 only on 'industrial' parcels (NULL is unconstrained → allowed)
--   emp_agriculture > 0 only on 'agricultural' or 'industrial' parcels (NULL is unconstrained → allowed)

SELECT parcel_id, land_development_category, emp_ind, emp_agriculture
FROM {{ ref('base_canvas_employment') }}
WHERE (
    land_development_category NOT IN ('industrial')
    AND land_development_category IS NOT NULL
    AND emp_ind > 0
) OR (
    land_development_category NOT IN ('agricultural', 'industrial')
    AND land_development_category IS NOT NULL
    AND emp_agriculture > 0
)
