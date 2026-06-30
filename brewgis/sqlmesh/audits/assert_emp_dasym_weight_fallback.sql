AUDIT (
  name assert_emp_dasym_weight_fallback,
  dialect postgres
);
-- Every parcel with Overture building footprints but zero non-residential sqft
-- MUST have emp_dasym_weight > 0 from the lot-size fallback, UNLESS the
-- authoritative source explicitly confirms zero non-residential area.
--
-- Without the fallback, employment allocation skips the parcel entirely,
-- concentrating all LEHD WAC block jobs on the few parcels with
-- Overture-tagged commercial buildings.
--
-- We LEFT JOIN authoritative_residential_area and exclude rows with
-- authoritative_non_residential_sqft IS NOT NULL because those are
-- confirmed-zero from the authoritative measurement — COALESCE returns
-- that 0 before reaching the NULLIF(..., 0) fallback, which is correct.
SELECT
  pdw.apn,
  pdw.residential_building_sqft,
  pdw.commercial_building_sqft,
  pdw.industrial_building_sqft,
  pdw.other_building_sqft,
  pdw.total_footprint_sqft,
  pdw.emp_dasym_weight,
  ar.authoritative_non_residential_sqft
FROM @this_model pdw
LEFT JOIN brewgis.assessor.authoritative_residential_area ar
  ON pdw.apn = ar.apn
WHERE COALESCE(pdw.residential_building_sqft, 0) > 0
  AND COALESCE(pdw.commercial_building_sqft, 0) = 0
  AND COALESCE(pdw.industrial_building_sqft, 0) = 0
  AND COALESCE(pdw.other_building_sqft, 0) = 0
  AND COALESCE(pdw.total_footprint_sqft, 0) > 0
  AND COALESCE(pdw.emp_dasym_weight, 0) = 0
  AND ar.authoritative_non_residential_sqft IS NULL;
