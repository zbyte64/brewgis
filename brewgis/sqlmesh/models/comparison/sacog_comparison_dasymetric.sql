MODEL (
  name brewgis.comparison.sacog_comparison_dasymetric,
  kind FULL,
  audits (
    not_null(columns := (parcel_id))
  )
);

-- SACOG Comparison Dasymetric Crosswalk — area-weighted assessor → SACOG parcel mapping.
--
-- Joins SACOG parcel geometries (sacog_parcel_shim) against assessor-derived
-- dasymetric weights (parcel_dasymetric_weights) + DU estimation
-- (parcel_du_estimation) using ST_Intersects and picks the best match per
-- SACOG parcel_id by largest intersection area.

SELECT DISTINCT ON (sp.parcel_id)
    sp.parcel_id,
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
FROM brewgis.comparison.sacog_parcel_shim sp
JOIN brewgis.assessor.parcel_dasymetric_weights dw
    ON ST_Intersects(sp.geometry, dw.geometry)
LEFT JOIN brewgis.assessor.parcel_du_estimation de
    ON dw.apn = de.apn
ORDER BY sp.parcel_id, COALESCE(ST_Area(ST_Intersection(ST_Envelope(sp.geometry), ST_Envelope(dw.geometry))), 0) DESC;

-- post_statements
@IF(@runtime_stage = 'evaluating',
  CREATE INDEX IF NOT EXISTS idx_sacog_comparison_dasymetric_parcel_id
  ON brewgis.comparison.sacog_comparison_dasymetric (parcel_id)
);
