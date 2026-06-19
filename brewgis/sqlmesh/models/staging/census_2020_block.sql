MODEL (
  name brewgis.staging.census_2020_block,
  kind FULL,
  audits (
    not_null(columns := (geoid))
  ),
  dialect postgres
);

-- Census 2020 PL94-171 → Census Block Demographics Table
--
-- Joins decennial Census block raw data with TIGER/Line block geometry.
-- PL94-171 redistricting data provides total population and housing units
-- at the census block level, the finest granularity available.
--
-- Note: PL94-171 does not include group quarters population (SF1 did,
-- but was replaced by ACS for socioeconomics). The total_group_quarters
-- column is included for schema compatibility but will always be 0.

WITH raw_data AS (
    SELECT
        geoid,
        total_population,
        total_housing_units
    FROM public.census_2020_block_raw
),
block_geometry AS (
    SELECT
        geoid,
        geometry
    FROM public.tiger_blocks
    WHERE vintage = '2020'
)
SELECT
    raw.geoid,
    COALESCE(raw.total_population, 0)::double precision AS total_population,
    COALESCE(raw.total_housing_units, 0)::double precision AS total_housing_units,
    -- PL94-171 does not include group quarters population; always 0.
    0.0::double precision AS total_group_quarters,
    bg.geometry
FROM raw_data raw
LEFT JOIN block_geometry bg
    ON raw.geoid = bg.geoid;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_census_2020_block_geometry
  ON brewgis.staging.census_2020_block USING GIST (geometry);
ANALYZE brewgis.staging.census_2020_block;
