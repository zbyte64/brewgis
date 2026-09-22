MODEL (
  name brewgis.@{scenario_schema}.@{model_table},
  kind FULL,
  description 'Per-parcel compactness index (0-100) from ranked density, connectivity and mixed use.',
  column_descriptions (
    parcel_id = 'Assessor parcel number (APN) of the parcel.',
    area_gross_acres = 'Gross parcel area (acres).',
    pop = 'Population allocated to the parcel (people).',
    population_density = 'Population divided by gross parcel area (people per acre).',
    intersection_density = 'Intersection density (intersections per km2).',
    land_development_category = 'Land development category (urban, compact, standard or rural).',
    emp = 'Employment allocated to the parcel (jobs).',
    density_score = 'Percentile rank of the parcel population density (0-1).',
    connectivity_score = 'Percentile rank of the parcel intersection density (0-1).',
    mixed_use_score = 'One when the parcel has both population and employment, else zero.',
    sprawl_index = 'Mean of the density, connectivity and mixed-use scores (0-100).',
    geometry = 'Parcel boundary geometry (EPSG:4326).'
  ),
  blueprints @analysis_blueprints('sprawl_index'),
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
    FROM @{scenario_schema}.core_end_state AS es
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
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_sprawl_index_geometry_')
  ON @this_model USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_sprawl_index_parcel_id_')
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
