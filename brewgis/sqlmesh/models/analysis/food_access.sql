MODEL (
  name brewgis.analysis.food_access,
  kind FULL,
);

WITH food_data AS (
    SELECT
        es.parcel_id,
        es.gross_acres,
        es.population,
        es.households,
        fi.healthy_count,
        fi.unhealthy_count,
        fi.mrfei,
        es.geom
    FROM brewgis.analysis.core_end_state AS es
    LEFT JOIN brewgis.analysis.food_access_inputs AS fi
        ON es.parcel_id = fi.parcel_id
)

SELECT
    parcel_id,
    gross_acres,
    population,
    households,
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
    geom
FROM food_data;


-- ------------------------------------------------------------
-- Sprawl Index (SX)
--   Per-parcel compactness/sprawl index (scored 0-100) from
--   population density, intersection connectivity, and land-use
--   mix (presence of both population and employment).
-- Source (dbt): brewgis/dbt_project/models/sprawl_index.sql
-- ------------------------------------------------------------

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_food_access_geom
  ON @this_model USING GIST (geom);
  CREATE INDEX IF NOT EXISTS idx_food_access_parcel_id
  ON @this_model USING btree (parcel_id);
ANALYZE @this_model;
