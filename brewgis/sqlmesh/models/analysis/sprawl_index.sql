MODEL (
  name brewgis.analysis.sprawl_index,
  kind FULL,
);

WITH parcel_scores AS (
    SELECT
        es.parcel_id,
        es.area_gross_acres,
        es.pop,
        COALESCE(es.pop / NULLIF(es.area_gross_acres, 0.0), 0.0) AS population_density,
        es.intersection_density,
        es.land_development_category,
        es.emp,
        es.geometry,
        -- Density score: PERCENT_RANK of population density
        PERCENT_RANK() OVER (
            ORDER BY COALESCE(es.pop / NULLIF(es.area_gross_acres, 0.0), 0.0)
        ) AS density_score,
        -- Connectivity score: PERCENT_RANK of intersection density
        PERCENT_RANK() OVER (
            ORDER BY COALESCE(es.intersection_density, 0.0)
        ) AS connectivity_score,
        -- Mixed-use score: 1.0 if both population and employment present
        CASE
            WHEN COALESCE(es.pop, 0.0) > 0.0
                AND COALESCE(es.emp, 0.0) > 0.0
            THEN 1.0
            ELSE 0.0
        END AS mixed_use_score
    FROM brewgis.analysis.core_end_state AS es
)

SELECT
    parcel_id,
    area_gross_acres,
    pop,
    population_density,
    intersection_density,
    land_development_category,
    emp,
    density_score,
    connectivity_score,
    mixed_use_score,
    -- Composite sprawl index: mean of three component scores scaled to 0-100
    COALESCE(
        (density_score + connectivity_score + mixed_use_score) / 3.0 * 100.0,
        0.0
    ) AS sprawl_index,
    geometry
FROM parcel_scores;


-- ------------------------------------------------------------
-- Housing Cost Burden
--   Housing cost burden per parcel using configurable ACS-derived
--   cost-burden rates applied to household counts.
-- Source (dbt): brewgis/dbt_project/models/housing_cost_burden.sql
-- ------------------------------------------------------------

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_sprawl_index_geometry_@snapshot_hash
  ON @this_model USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS idx_sprawl_index_parcel_id_@snapshot_hash
  ON @this_model USING btree (parcel_id);
ANALYZE @this_model;
