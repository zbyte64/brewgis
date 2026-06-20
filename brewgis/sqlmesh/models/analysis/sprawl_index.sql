MODEL (
  name brewgis.analysis.sprawl_index,
  kind FULL,
);

WITH parcel_scores AS (
    SELECT
        es.parcel_id,
        es.gross_acres,
        es.population,
        COALESCE(es.population / NULLIF(es.gross_acres, 0.0), 0.0) AS population_density,
        es.intersection_density,
        es.land_dev_category,
        es.employment_total,
        es.geom,
        -- Density score: PERCENT_RANK of population density
        PERCENT_RANK() OVER (
            ORDER BY COALESCE(es.population / NULLIF(es.gross_acres, 0.0), 0.0)
        ) AS density_score,
        -- Connectivity score: PERCENT_RANK of intersection density
        PERCENT_RANK() OVER (
            ORDER BY COALESCE(es.intersection_density, 0.0)
        ) AS connectivity_score,
        -- Mixed-use score: 1.0 if both population and employment present
        CASE
            WHEN COALESCE(es.population, 0.0) > 0.0
                AND COALESCE(es.employment_total, 0.0) > 0.0
            THEN 1.0
            ELSE 0.0
        END AS mixed_use_score
    FROM brewgis.analysis.core_end_state AS es
)

SELECT
    parcel_id,
    gross_acres,
    population,
    population_density,
    intersection_density,
    land_dev_category,
    employment_total,
    density_score,
    connectivity_score,
    mixed_use_score,
    -- Composite sprawl index: mean of three component scores scaled to 0-100
    COALESCE(
        (density_score + connectivity_score + mixed_use_score) / 3.0 * 100.0,
        0.0
    ) AS sprawl_index,
    geom
FROM parcel_scores;


-- ------------------------------------------------------------
-- Housing Cost Burden
--   Housing cost burden per parcel using configurable ACS-derived
--   cost-burden rates applied to household counts.
-- Source (dbt): brewgis/dbt_project/models/housing_cost_burden.sql
-- ------------------------------------------------------------

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_sprawl_index_geom
  ON brewgis.analysis.sprawl_index USING GIST (geom);
  CREATE INDEX IF NOT EXISTS idx_sprawl_index_parcel_id
  ON brewgis.analysis.sprawl_index (parcel_id);
ANALYZE brewgis.analysis.sprawl_index;
