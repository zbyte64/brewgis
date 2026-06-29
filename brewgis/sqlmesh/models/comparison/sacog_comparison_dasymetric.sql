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
-- pre-computed intersection table. When multiple SACOG parcels share the same
-- assessor APN, DU, building sqft, and dasymetric weights are allocated
-- proportionally by intersection area (Section 4.2 of methodology).

WITH apn_weights AS (
    SELECT
        si.parcel_id,
        si.apn,
        si.intersect_area_sqft,
        SUM(si.intersect_area_sqft) OVER (PARTITION BY si.apn) AS apn_total_area,
        CASE
            WHEN SUM(si.intersect_area_sqft) OVER (PARTITION BY si.apn) > 0
            THEN si.intersect_area_sqft
                 / SUM(si.intersect_area_sqft) OVER (PARTITION BY si.apn)
            ELSE 1.0
        END AS apn_weight
    FROM brewgis.comparison.dasymetric_intersections si
)
SELECT
    aw.parcel_id,
    dw.apn,
    -- Allocate scalar quantities proportionally (Section 4.2)
    dw.lot_size_acres * aw.apn_weight AS lot_size_acres,
    -- Categorical labels: pass through unchanged (one-per-APN)
    dw.land_development_category,
    dw.built_form_key,
    dw.du_subtype,
    dw.is_residential,
    -- Building sqft: allocate proportionally
    dw.actual_living_sqft  * aw.apn_weight AS actual_living_sqft,
    dw.actual_building_sqft * aw.apn_weight AS actual_building_sqft,
    dw.residential_building_sqft * aw.apn_weight AS residential_building_sqft,
    dw.commercial_building_sqft  * aw.apn_weight AS commercial_building_sqft,
    dw.industrial_building_sqft  * aw.apn_weight AS industrial_building_sqft,
    dw.other_building_sqft       * aw.apn_weight AS other_building_sqft,
    dw.total_footprint_sqft      * aw.apn_weight AS total_footprint_sqft,
    -- Building count: allocate then round to nearest integer
    ROUND(dw.building_count * aw.apn_weight)::int AS building_count,
    -- Ratio/density columns: pass through unchanged (ratios do not scale)
    dw.footprint_ratio,
    dw.max_levels,
    dw.intersection_density,
    -- Dasymetric weights: allocate proportionally
    dw.pop_dasym_weight * aw.apn_weight AS pop_dasym_weight,
    dw.emp_dasym_weight * aw.apn_weight AS emp_dasym_weight,
    -- DU estimation: allocate proportionally (Section 5)
    de.du          * aw.apn_weight AS du,
    de.hh_size                              AS hh_size,        -- rate, not allocated
    de.vacancy_rate                         AS vacancy_rate,    -- rate, not allocated
    de.pop_dasym_weight * aw.apn_weight AS du_pop_dasym_weight,
    de.hh_dasym_weight  * aw.apn_weight AS hh_dasym_weight,
    de.hh               * aw.apn_weight AS hh,
    sp.geometry
FROM apn_weights aw
JOIN brewgis.comparison.sacog_parcel_shim sp ON aw.parcel_id = sp.parcel_id
JOIN brewgis.assessor.parcel_dasymetric_weights dw ON aw.apn = dw.apn
LEFT JOIN brewgis.assessor.parcel_du_estimation de ON aw.apn = de.apn;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_sacog_comparison_dasymetric_geom
  ON @this_model USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS idx_sacog_comparison_dasymetric_parcel_id
  ON @this_model USING btree (parcel_id);
  CREATE INDEX IF NOT EXISTS idx_sacog_comparison_dasymetric_apn
  ON @this_model USING btree (apn);
ANALYZE @this_model;
