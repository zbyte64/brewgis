MODEL (
  name brewgis.@{scenario_schema}.@{model_table},
  kind FULL,
  description 'Per-parcel stormwater runoff from impervious cover using the Simple Method, and its change.',
  column_descriptions (
    parcel_id = 'Assessor parcel number (APN) of the parcel.',
    impervious_acres = 'Impervious area from the land consumption model (acres).',
    impervious_pct = 'Impervious area as a share of the parcel (% as 0-100).',
    runoff_coefficient = 'Runoff coefficient: 0.05 plus 0.009 per impervious percent (unitless).',
    runoff_volume_acre_ft = 'Annual runoff volume from precipitation and the coefficient (acre-feet).',
    runoff_baseline_acre_ft = 'Baseline annual runoff (acre-feet); currently equals the scenario value.',
    geometry = 'Parcel boundary geometry (EPSG:4326).',
    runoff_change_acre_ft = 'Scenario runoff minus baseline runoff (acre-feet per year).',
    runoff_change_pct = 'Runoff change as a share of the baseline (% as 0-100); zero without one.'
  ),
  blueprints @analysis_blueprints('stormwater_runoff'),
);

WITH land_data AS (
    SELECT
        lc.parcel_id,
        lc.area_gross_acres,
        lc.impervious_acres,
        lc.impervious_pct,
        es.geometry,
        0.0::double precision AS impervious_acres_baseline
        -- Note: impervious-acres increment not yet modeled in core_increment;
        -- baseline defaults to 0, making pct_baseline = pct below
    FROM @{scenario_schema}.land_consumption AS lc
    LEFT JOIN @{scenario_schema}.core_end_state AS es
        ON lc.parcel_id = es.parcel_id
),

-- Compute baseline impervious percentage from increment delta
baseline AS (
    SELECT
        parcel_id,
        area_gross_acres,
        impervious_acres,
        impervious_pct,
        geometry,
        GREATEST(
            impervious_pct
            - CASE
                WHEN area_gross_acres > 0
                    THEN impervious_acres_baseline / area_gross_acres * 100.0
                ELSE 0.0
            END,
            0.0
        ) AS impervious_pct_baseline
    FROM land_data
),

-- Compute runoff volumes
runoff AS (
    SELECT
        parcel_id,
        impervious_acres,
        impervious_pct,
        geometry,
        0.05 + 0.009 * impervious_pct AS runoff_coefficient,
        @blueprint_var('stormwater_annual_precipitation_in') * 0.9
        * (0.05 + 0.009 * impervious_pct)
        * area_gross_acres / 12.0 AS runoff_volume_acre_ft,
        0.05 + 0.009 * impervious_pct_baseline AS runoff_coefficient_baseline,
        @blueprint_var('stormwater_annual_precipitation_in') * 0.9
        * (0.05 + 0.009 * impervious_pct_baseline)
        * area_gross_acres / 12.0 AS runoff_baseline_acre_ft
    FROM baseline
)

SELECT
    parcel_id,
    impervious_acres,
    impervious_pct,
    runoff_coefficient,
    runoff_volume_acre_ft,
    runoff_baseline_acre_ft,
    geometry,
    runoff_volume_acre_ft - runoff_baseline_acre_ft AS runoff_change_acre_ft,
    CASE
        WHEN runoff_baseline_acre_ft > 0
            THEN
                (runoff_volume_acre_ft - runoff_baseline_acre_ft)
                / runoff_baseline_acre_ft * 100.0
        ELSE 0.0
    END AS runoff_change_pct
FROM runoff;


-- ------------------------------------------------------------
-- Tree Canopy / Urban Heat Island
--   Parcel-level tree canopy cover percentage and surface
--   temperature proxy using published urban heat island
--   relationships (~1F reduction per 10% canopy increase).
-- Source (dbt): brewgis/dbt_project/models/tree_canopy.sql
-- ------------------------------------------------------------

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_stormwater_runoff_geometry_')
  ON @this_model USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_stormwater_runoff_parcel_id_')
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
