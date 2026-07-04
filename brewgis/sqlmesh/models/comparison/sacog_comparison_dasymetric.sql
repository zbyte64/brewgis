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
-- APN, or one SACOG parcel intersects multiple APNs, scalar quantities (sqft,
-- DU, weights) are allocated proportionally by intersection area then summed
-- per SACOG parcel.  Categorical columns (built_form_key, du_subtype) are
-- taken from the APN with the largest intersection area for that parcel.
--
-- The aggregation by parcel_id produces exactly one row per SACOG parcel,
-- which satisfies the INCREMENTAL_BY_UNIQUE_KEY constraint in downstream
-- base_canvas_geometry.

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
),

scaled AS (
    SELECT
        aw.parcel_id,
        aw.apn,
        aw.apn_weight,
        aw.intersect_area_sqft,
        ROW_NUMBER() OVER (
            PARTITION BY aw.parcel_id
            ORDER BY aw.intersect_area_sqft DESC
        ) AS rn,
        sp.geometry,
        -- Allocate scalar quantities proportionally (Section 4.2 methodology)
        dw.lot_size_acres          * aw.apn_weight AS lot_size_acres,
        dw.actual_living_sqft      * aw.apn_weight AS actual_living_sqft,
        dw.actual_building_sqft    * aw.apn_weight AS actual_building_sqft,
        dw.residential_building_sqft * aw.apn_weight AS residential_building_sqft,
        dw.commercial_building_sqft  * aw.apn_weight AS commercial_building_sqft,
        dw.industrial_building_sqft  * aw.apn_weight AS industrial_building_sqft,
        dw.other_building_sqft       * aw.apn_weight AS other_building_sqft,
        dw.total_footprint_sqft      * aw.apn_weight AS total_footprint_sqft,
        -- Building count: allocate then round
        ROUND(dw.building_count * aw.apn_weight)::int AS building_count,
        -- Dasymetric weights: allocate proportionally
        dw.pop_dasym_weight * aw.apn_weight AS pop_dasym_weight,
        dw.emp_dasym_weight * aw.apn_weight AS emp_dasym_weight,
        -- DU estimation: allocate proportionally
        de.du              * aw.apn_weight AS du,
        de.pop_dasym_weight * aw.apn_weight AS du_pop_dasym_weight,
        de.hh_dasym_weight  * aw.apn_weight AS hh_dasym_weight,
        de.hh               * aw.apn_weight AS hh,
        -- Categorical labels from the dominant APN
        dw.land_development_category,
        dw.built_form_key,
        dw.du_subtype,
        dw.is_residential,
        -- Ratio/density columns (unchanged per APN)
        dw.footprint_ratio,
        dw.max_levels,
        dw.intersection_density,
        -- Rates (unchanged per APN)
        de.hh_size,
        de.vacancy_rate
    FROM apn_weights aw
    JOIN brewgis.comparison.sacog_parcel_shim sp
        ON aw.parcel_id = sp.parcel_id
    JOIN brewgis.assessor.parcel_dasymetric_weights dw
        ON aw.apn = dw.apn
    LEFT JOIN brewgis.assessor.parcel_du_estimation de
        ON aw.apn = de.apn
)

SELECT
    parcel_id,
    geometry,
    -- Scalars: sum allocated contributions from all matching APNs
    SUM(lot_size_acres) AS lot_size_acres,
    SUM(actual_living_sqft) AS actual_living_sqft,
    SUM(actual_building_sqft) AS actual_building_sqft,
    SUM(residential_building_sqft) AS residential_building_sqft,
    SUM(commercial_building_sqft) AS commercial_building_sqft,
    SUM(industrial_building_sqft) AS industrial_building_sqft,
    SUM(other_building_sqft) AS other_building_sqft,
    SUM(total_footprint_sqft) AS total_footprint_sqft,
    SUM(building_count) AS building_count,
    SUM(pop_dasym_weight) AS pop_dasym_weight,
    SUM(emp_dasym_weight) AS emp_dasym_weight,
    SUM(du) AS du,
    SUM(du_pop_dasym_weight) AS du_pop_dasym_weight,
    SUM(hh_dasym_weight) AS hh_dasym_weight,
    SUM(hh) AS hh,
    -- APN identifier: from the dominant APN (largest intersection area)
    MAX(CASE WHEN rn = 1 THEN apn END) AS apn,
    -- Categoricals: pick from the APN with the largest intersection area
    MAX(CASE WHEN rn = 1 THEN land_development_category END)
        AS land_development_category,
    MAX(CASE WHEN rn = 1 THEN built_form_key END) AS built_form_key,
    MAX(CASE WHEN rn = 1 THEN du_subtype END) AS du_subtype,
    MAX(CASE WHEN rn = 1 THEN is_residential END)
        AS is_residential,
    -- Ratio/density: weighted by apn_weight (sum of weights per parcel)
    SUM(footprint_ratio * apn_weight) / NULLIF(SUM(apn_weight), 0) AS footprint_ratio,
    SUM(max_levels * apn_weight) / NULLIF(SUM(apn_weight), 0) AS max_levels,
    SUM(intersection_density * apn_weight) / NULLIF(SUM(apn_weight), 0) AS intersection_density,
    -- Rates: weighted by apn_weight
    SUM(hh_size * apn_weight) / NULLIF(SUM(apn_weight), 0) AS hh_size,
    SUM(vacancy_rate * apn_weight) / NULLIF(SUM(apn_weight), 0) AS vacancy_rate
FROM scaled
GROUP BY parcel_id, geometry;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_sacog_comparison_dasymetric_geom_@snapshot_hash
  ON @this_model USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS idx_sacog_comparison_dasymetric_parcel_id_@snapshot_hash
  ON @this_model USING btree (parcel_id);
  CREATE INDEX IF NOT EXISTS idx_sacog_comparison_dasymetric_apn_@snapshot_hash
  ON @this_model USING btree (apn);
ANALYZE @this_model;
