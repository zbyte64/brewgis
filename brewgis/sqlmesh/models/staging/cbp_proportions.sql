MODEL (
  name brewgis.staging.cbp_proportions,
  kind FULL,
  audits (
    not_null(columns := (state_fips, county_fips))
  )
);

-- CBP County Business Patterns → NAICS sub-sector proportions.
--
-- Computes within-sector employment proportions from raw CBP data.
-- These proportions are used by wac_block_raw.sql to split LODES
-- CNS employment into NAICS-based sub-sectors.
--
-- The output is a single row per county with proportion columns:
--   cbp_11  = NAICS 11 (agriculture) share of CNS01 goods-producing
--   cbp_21  = NAICS 21 (extraction) share of CNS01
--   cbp_721 = NAICS 721 (accommodation) share of CNS13
--
-- When CBP data is unavailable, national default ratios are used.
--
-- Replaces the Python _compute_cbp_proportions function in lehd_fetcher.py.
--
-- Variables:
--   @state_fips    — Two-digit state FIPS code
--   @county_fips   — Three-digit county code

WITH raw_emp AS (
  SELECT
    TRIM(c.naics_code) AS naics_code,
    SUM(c.emp) AS total_emp
  FROM brewgis.staging.cbp_raw c
  WHERE c.year = CAST(@acs_year AS INTEGER)
    AND c.state = @state_fips
    AND c.emp IS NOT NULL
    AND c.naics_code IS NOT NULL
    AND TRIM(c.naics_code) <> ''
  GROUP BY TRIM(c.naics_code)
),
-- Extract 2-digit and 3-digit NAICS prefixes
naics_prefix AS (
  SELECT
    naics_code,
    total_emp,
    LEFT(naics_code, 2) AS prefix_2,
    LEFT(naics_code, 3) AS prefix_3
  FROM raw_emp
),
-- CNS01 goods-producing: NAICS 11, 21, 23
cns01 AS (
  SELECT
    COALESCE(SUM(CASE WHEN prefix_2 = '11' THEN total_emp END), 0) AS emp_11,
    COALESCE(SUM(CASE WHEN prefix_2 = '21' THEN total_emp END), 0) AS emp_21,
    COALESCE(SUM(CASE WHEN prefix_2 = '23' THEN total_emp END), 0) AS emp_23,
    COALESCE(SUM(CASE WHEN prefix_2 IN ('11', '21', '23') THEN total_emp END), 0) AS goods_total
  FROM naics_prefix
),
-- CNS03 trade/transport/utilities: NAICS 22, 42, 44, 45, 48, 49
cns03 AS (
  SELECT
    COALESCE(SUM(CASE WHEN prefix_2 = '22' THEN total_emp END), 0) AS emp_22,
    COALESCE(SUM(CASE WHEN prefix_2 = '42' THEN total_emp END), 0) AS emp_42,
    COALESCE(SUM(CASE WHEN prefix_2 = '44' THEN total_emp END), 0) AS emp_44,
    COALESCE(SUM(CASE WHEN prefix_2 = '45' THEN total_emp END), 0) AS emp_45,
    COALESCE(SUM(CASE WHEN prefix_2 = '48' THEN total_emp END), 0) AS emp_48,
    COALESCE(SUM(CASE WHEN prefix_2 = '49' THEN total_emp END), 0) AS emp_49,
    COALESCE(SUM(CASE WHEN prefix_2 IN ('22', '42', '44', '45', '48', '49') THEN total_emp END), 0) AS ttu_total
  FROM naics_prefix
),
-- CNS13 accommodation/food: NAICS 721, 722 (3-digit)
cns13 AS (
  SELECT
    COALESCE(SUM(CASE WHEN prefix_3 = '721' THEN total_emp END), 0) AS emp_721,
    COALESCE(SUM(CASE WHEN prefix_3 = '722' THEN total_emp END), 0) AS emp_722,
    COALESCE(SUM(CASE WHEN prefix_3 IN ('721', '722') THEN total_emp END), 0) AS acc_food_total
  FROM naics_prefix
)
SELECT
  @state_fips AS state_fips,
  @county_fips AS county_fips,
  -- CNS01 proportions
  CASE
    WHEN cns01.goods_total > 0 THEN ROUND(cns01.emp_11 / cns01.goods_total, 6)
    ELSE 0.05  -- national default
  END AS cbp_11,
  CASE
    WHEN cns01.goods_total > 0 THEN ROUND(cns01.emp_21 / cns01.goods_total, 6)
    ELSE 0.02  -- national default
  END AS cbp_21,
  -- CNS03 proportions
  CASE
    WHEN cns03.ttu_total > 0 THEN ROUND(cns03.emp_22 / cns03.ttu_total, 6)
    ELSE 0.02  -- national default
  END AS cbp_22,
  CASE
    WHEN cns03.ttu_total > 0 THEN ROUND(cns03.emp_42 / cns03.ttu_total, 6)
    ELSE 0.10  -- national default
  END AS cbp_42,
  CASE
    WHEN cns03.ttu_total > 0 THEN ROUND(cns03.emp_48 / cns03.ttu_total, 6)
    ELSE 0.04  -- national default
  END AS cbp_48,
  CASE
    WHEN cns03.ttu_total > 0 THEN ROUND(cns03.emp_49 / cns03.ttu_total, 6)
    ELSE 0.02  -- national default
  END AS cbp_49,
  -- CNS13 proportions
  CASE
    WHEN cns13.acc_food_total > 0 THEN ROUND(cns13.emp_721 / cns13.acc_food_total, 6)
    ELSE 0.40  -- national default
  END AS cbp_721
FROM cns01, cns03, cns13;
