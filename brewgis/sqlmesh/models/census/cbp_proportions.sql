MODEL (
  name brewgis.@{region}.cbp_proportions,
  kind FULL,
  description 'County-level CBP NAICS 721 accommodation share of NAICS 72 used to split LODES CNS18 accommodation and food services jobs, one row per county.',
  column_descriptions (
    state_fips = 'Two-digit state FIPS code the proportions were computed for (@state_fips).',
    county_fips = 'Three-digit county code the proportions were computed for (@county_fips).',
    cbp_721 = 'NAICS 721 accommodation share of NAICS 72 (LODES CNS18) employment, national default 0.40 without CBP.'
  ),
  audits (
    not_null(columns := (state_fips, county_fips))
  ),
  blueprints @region_blueprints()
);

-- CBP County Business Patterns → NAICS 721 share of NAICS 72.
--
-- LODES WAC reports NAICS 72 as a single sector (CNS18); wac_block_raw.sql
-- splits it into accommodation (721) and food services (722) with this
-- share. Every other LODES CNS column is already a single NAICS sector.
--
-- When CBP data is unavailable, the national default ratio is used.
--
-- Variables:
--   @state_fips    — Two-digit state FIPS code
--   @county_fips   — Three-digit county code

WITH raw_emp AS (
  SELECT
    TRIM(c.naics_code) AS naics_code,
    SUM(c.emp) AS total_emp
  FROM brewgis.@{region}.cbp_raw c
  WHERE c.year = CAST(@acs_year AS INTEGER)
    AND c.state = @state_fips
    AND c.emp IS NOT NULL
    AND c.naics_code IS NOT NULL
    AND TRIM(c.naics_code) <> ''
  GROUP BY TRIM(c.naics_code)
),
-- CNS18 accommodation/food: NAICS 721, 722 (3-digit)
cns18 AS (
  SELECT
    COALESCE(SUM(CASE WHEN LEFT(naics_code, 3) = '721' THEN total_emp END), 0) AS emp_721,
    COALESCE(SUM(CASE WHEN LEFT(naics_code, 3) IN ('721', '722') THEN total_emp END), 0) AS acc_food_total
  FROM raw_emp
)
SELECT
  @state_fips AS state_fips,
  @county_fips AS county_fips,
  CASE
    WHEN cns18.acc_food_total > 0 THEN ROUND(cns18.emp_721 / cns18.acc_food_total, 6)
    ELSE 0.40  -- national default
  END AS cbp_721
FROM cns18;
