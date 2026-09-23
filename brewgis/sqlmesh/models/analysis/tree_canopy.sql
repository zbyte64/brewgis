MODEL (
  name brewgis.@{scenario_schema}.@{model_table},
  kind FULL,
  description 'Per-parcel tree canopy percentage from the land development category, with a heat exposure score.',
  column_descriptions (
    parcel_id = 'Assessor parcel number (APN) of the parcel.',
    area_gross_acres = 'Gross parcel area (acres).',
    pop = 'Population allocated to the parcel (people).',
    hh = 'Households allocated to the parcel (households).',
    canopy_pct = 'Assumed canopy cover from the land development category (% as 0-100).',
    surface_temp_f = 'Surface temperature proxy, baseline minus 1 F per 10 percent canopy (F).',
    heat_exposure_score = 'Heat exposure score, 100 minus 4 per canopy percent (0-100, worse higher).',
    geometry = 'Parcel boundary geometry (EPSG:4326).'
  ),
  blueprints @analysis_blueprints('tree_canopy')
);

WITH parcel_canopy AS (
    SELECT
        es.parcel_id,
        es.area_gross_acres,
        es.pop,
        es.hh,
        es.geometry,
        -- Canopy cover: estimate from land use category
        CASE
            WHEN es.land_development_category = 'compact' THEN 25.0  -- dense urban (low canopy)
            WHEN es.land_development_category = 'urban' THEN 15.0
            WHEN es.land_development_category = 'standard' THEN 30.0  -- suburban (moderate)
            WHEN es.land_development_category = 'rural' THEN 45.0     -- rural (high canopy)
            ELSE 20.0
        END AS canopy_pct
    FROM @{scenario_schema}.core_end_state AS es
)
SELECT
    parcel_id,
    area_gross_acres,
    pop,
    hh,
    canopy_pct,
    -- Surface temp proxy: baseline minus cooling effect
    ROUND((@blueprint_var('tree_canopy_baseline_temp') - (canopy_pct / 10.0 * @blueprint_var('tree_canopy_temp_per_10pct')))::numeric, 1) AS surface_temp_f,
    -- Heat exposure score: 0-100 (higher = worse, inverse of canopy)
    ROUND(GREATEST(0.0, 100.0 - (canopy_pct * 4.0))::numeric, 1) AS heat_exposure_score,
    geometry
FROM parcel_canopy;


-- ------------------------------------------------------------
-- Food Access (H3 — mRFEI)
--   Modified Retail Food Environment Index (mRFEI) per parcel
--   using OSM Points of Interest data.
-- Source (dbt): brewgis/dbt_project/models/food_access.sql
-- ------------------------------------------------------------

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_tree_canopy_geometry_')
  ON @this_model USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_tree_canopy_parcel_id_')
  ON @this_model USING btree (parcel_id);
ANALYZE @this_model;


-- Publish this model's result view where the Layers, Martin and UI paths read
-- it. The view selects from this model's prod virtual view (never its physical
-- table), so promoting a non-prod environment never repoints it. See
-- sqlmesh/macros/analysis_blueprints.py.
ON_VIRTUAL_UPDATE_BEGIN;

CREATE SCHEMA IF NOT EXISTS "@{result_schema}";

CREATE OR REPLACE VIEW "@{result_schema}"."@{model_table}" AS
SELECT * FROM @{scenario_schema}."@{model_table}";

ON_VIRTUAL_UPDATE_END;
