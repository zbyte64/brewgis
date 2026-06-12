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
-- dasymetric weights (parcel_dasymetric_weights) using ST_Intersects and picks
-- the best match per SACOG parcel_id by largest intersection area.

SELECT DISTINCT ON (sp.parcel_id)
    sp.parcel_id,
    dw.lot_size_acres,
    dw.land_development_category,
    dw.actual_living_sqft,
    dw.actual_building_sqft,
    dw.estimated_living_sqft,
    dw.estimated_building_sqft,
    dw.footprint_imputed_living_sqft,
    dw.footprint_imputed_building_sqft,
    dw.impervious_fraction,
    dw.intersection_density,
    dw.pop_dasym_weight,
    dw.emp_dasym_weight,
    dw.du_subtype,
    dw.du_dasym_weight,
    sp.geometry
FROM brewgis.comparison.sacog_parcel_shim sp
JOIN brewgis.assessor.parcel_dasymetric_weights dw
    ON ST_Intersects(sp.geometry, dw.geometry)
ORDER BY sp.parcel_id, COALESCE(ST_Area(ST_Intersection(ST_Envelope(sp.geometry), ST_Envelope(dw.geometry))), 0) DESC;

-- post_statements
@IF(@runtime_stage = 'evaluating',
  CREATE INDEX IF NOT EXISTS idx_sacog_comparison_dasymetric_parcel_id
  ON brewgis.comparison.sacog_comparison_dasymetric (parcel_id)
);
