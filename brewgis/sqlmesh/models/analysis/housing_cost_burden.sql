MODEL (
  name brewgis.@{scenario_schema}.@{model_table},
  kind FULL,
  description 'Per-parcel cost-burdened and severely cost-burdened household counts from configurable rates.',
  column_descriptions (
    parcel_id = 'Assessor parcel number (APN) of the parcel.',
    area_gross_acres = 'Gross parcel area (acres).',
    pop = 'Population allocated to the parcel (people).',
    hh = 'Households allocated to the parcel (households).',
    du = 'Dwelling units allocated to the parcel (units).',
    cost_burdened_hh = 'Households times the configured burden rate (households).',
    severely_cost_burdened_hh = 'Households times the configured severe burden rate (households).',
    cost_burden_pct = 'Cost-burdened households as a share of households (% as 0-100).',
    cost_burden_category = 'Band: low_burden, cost_burdened or severely_cost_burdened.',
    geometry = 'Parcel boundary geometry (EPSG:4326).'
  ),
  blueprints @analysis_blueprints('housing_cost_burden'),
);

SELECT
    es.parcel_id,
    es.area_gross_acres,
    es.pop,
    es.hh,
    es.du,
    -- Cost-burdened households
    COALESCE(es.hh * @housing_cost_burden_rate, 0.0) AS cost_burdened_hh,
    -- Severely cost-burdened households
    COALESCE(es.hh * @housing_severe_burden_rate, 0.0) AS severely_cost_burdened_hh,
    -- Cost burden percentage
    COALESCE(
        (es.hh * @housing_cost_burden_rate) / NULLIF(es.hh, 0) * 100.0,
        0.0
    ) AS cost_burden_pct,
    -- Cost burden category
    CASE
        WHEN COALESCE(es.hh, 0) = 0 THEN 'low_burden'
        WHEN (es.hh * @housing_cost_burden_rate) / NULLIF(es.hh, 0) * 100.0 < 30.0
            THEN 'low_burden'
        WHEN (es.hh * @housing_cost_burden_rate) / NULLIF(es.hh, 0) * 100.0 <= 50.0
            THEN 'cost_burdened'
        ELSE 'severely_cost_burdened'
    END AS cost_burden_category,
    es.geometry
FROM @{scenario_schema}.core_end_state AS es;


-- ------------------------------------------------------------
-- Displacement Risk / Gentrification Typology
--   Per-parcel displacement risk using Urban Displacement
--   Project (UDP) methodology: four equity indicators yield a
--   vulnerability score (0-4) mapped to risk categories.
-- Source (dbt): brewgis/dbt_project/models/displacement_risk.sql
-- ------------------------------------------------------------

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_housing_cost_burden_geometry_')
  ON @this_model USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_housing_cost_burden_parcel_id_')
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
