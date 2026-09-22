MODEL (
  name brewgis.@{scenario_schema}.@{model_table},
  kind FULL,
  blueprints @analysis_blueprints('food_access'),
);

WITH food_data AS (
    SELECT
        es.parcel_id,
        es.area_gross_acres,
        es.pop,
        es.hh,
        fi.healthy_count,
        fi.unhealthy_count,
        fi.mrfei,
        es.geometry
    FROM @{scenario_schema}.core_end_state AS es
    LEFT JOIN @{scenario_schema}.food_access_inputs AS fi
        ON es.parcel_id = fi.parcel_id
)

SELECT
    parcel_id,
    area_gross_acres,
    pop,
    hh,
    COALESCE(healthy_count, 0) AS healthy_count,
    COALESCE(unhealthy_count, 0) AS unhealthy_count,
    mrfei,
    COALESCE(mrfei < 25, FALSE) AS food_desert,
    CASE
        WHEN mrfei IS NULL THEN NULL
        WHEN mrfei < 25 THEN 'food_desert'
        WHEN mrfei < 50 THEN 'low_access'
        WHEN mrfei < 75 THEN 'moderate_access'
        ELSE 'high_access'
    END AS food_access_category,
    geometry
FROM food_data;


-- ------------------------------------------------------------
-- Sprawl Index (SX)
--   Per-parcel compactness/sprawl index (scored 0-100) from
--   population density, intersection connectivity, and land-use
--   mix (presence of both population and employment).
-- Source (dbt): brewgis/dbt_project/models/sprawl_index.sql
-- ------------------------------------------------------------

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_food_access_geometry_')
  ON @this_model USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_food_access_parcel_id_')
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
