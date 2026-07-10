AUDIT (
  name assert_bldg_area_employment_targeted,
  dialect postgres
);
-- Parcels with bldg_area_medical_services > 0 must have either:
-- 1. commercial_building_sqft > 0 (assessor-derived building footprint), OR
-- 2. built_form_key is a non-residential bt__ class (commercial/employment/civic/mixed)
--
-- When employment is spread to parcels without commercial characteristics,
-- every parcel type gets the same employment density, inflating building
-- area estimates by orders of magnitude.
--
-- Uses a 40% threshold: if >40% of medical building area falls on
-- parcels without commercial characteristics, it signals poor targeting.
WITH
violations AS (
    SELECT
        parcel_id,
        bldg_area_medical_services,
        commercial_building_sqft,
        built_form_key
    FROM @this_model
    WHERE bldg_area_medical_services > 0
      AND COALESCE(commercial_building_sqft, 0) <= 0
      AND COALESCE(built_form_key, '') NOT IN ('bt__communityneighborhood_retail','bt__communityneighborhood_commercial','bt__communityneighborhood_commercialoffice','bt__regional_retail','bt__residentialretail_mixed_use_low','bt__residentialretail_mixed_use_high','bt__moderate_intensity_office','bt__high_intensity_office','bt__cbd_office','bt__light_industrialoffice','bt__hotel','bt__light_industrial','bt__heavy_industrial','bt__agricultural_processingretail_employment','bt__agriculture','bt__publicquasi_public','bt__civic_institution','bt__k_12_school','bt__college_university','bt__medical_facility','bt__park_and_open_space','bt__airport','bt__parking_lot','bt__parking_structure')
),
summary AS (
    SELECT
        COUNT(*) AS violation_count,
        SUM(v.bldg_area_medical_services) AS violation_area
    FROM violations v
),
total_medical AS (
    SELECT SUM(bldg_area_medical_services) AS total_area
    FROM @this_model
    WHERE bldg_area_medical_services > 0
)
SELECT
    s.violation_count,
    s.violation_area,
    t.total_area,
    ROUND((100.0 * s.violation_area / NULLIF(t.total_area, 0))::numeric, 1) AS pct_violation_area
FROM summary s, total_medical t
WHERE t.total_area > 0
  AND 100.0 * s.violation_area / t.total_area > 40.0;
