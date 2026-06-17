MODEL (
  name brewgis.comparison.sacog_comparison_dasymetric,
  kind FULL,
  audits (
    not_null(columns := (parcel_id))
  )
);

-- SACOG Comparison Dasymetric Crosswalk — enriched from pre-computed intersections.
--
-- Enriches SACOG parcels with dasymetric weights and DU estimation via the
-- pre-computed intersection table (no spatial join at this stage — the
-- expensive ST_Intersects + ST_Intersection is in
-- dasymetric_intersections).
--
-- Output columns match the original single-stage model schema.

SELECT
    si.parcel_id,
    dw.apn,
    dw.lot_size_acres,
    dw.land_development_category,
    dw.built_form_key,
    dw.du_subtype,
    dw.is_residential,
    dw.actual_living_sqft,
    dw.actual_building_sqft,
    dw.residential_building_sqft,
    dw.commercial_building_sqft,
    dw.industrial_building_sqft,
    dw.other_building_sqft,
    dw.total_footprint_sqft,
    dw.building_count,
    dw.footprint_ratio,
    dw.max_levels,
    dw.intersection_density,
    dw.impervious_fraction,
    dw.pop_dasym_weight,
    dw.emp_dasym_weight,
    -- DU estimation columns
    de.du,
    de.hh_size,
    de.vacancy_rate,
    de.pop_dasym_weight AS du_pop_dasym_weight,
    de.hh_dasym_weight,
    de.hh,
    sp.geometry
FROM brewgis.comparison.dasymetric_intersections si
JOIN brewgis.comparison.sacog_parcel_shim sp ON si.parcel_id = sp.parcel_id
JOIN brewgis.assessor.parcel_dasymetric_weights dw ON si.apn = dw.apn
LEFT JOIN brewgis.assessor.parcel_du_estimation de ON si.apn = de.apn;

-- post_statements
@IF(@runtime_stage = 'evaluating',
  CREATE INDEX IF NOT EXISTS idx_sacog_comparison_dasymetric_parcel_id
  ON brewgis.comparison.sacog_comparison_dasymetric (parcel_id)
);
