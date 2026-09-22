MODEL (
  name brewgis.sacog.weighted_means,
  kind FULL,
  description 'Population-weighted means of base-canvas density and rate metrics: SUM(metric * pop) / SUM(pop).',
  column_descriptions (
    source = 'Source label for the row (literal brewgis).',
    median_income_wavg = 'Population-weighted mean of base-canvas median household income ($ per year).',
    pct_minority_wavg = 'Population-weighted mean of base-canvas percent people of color (% as 0-100).',
    pct_college_educated_wavg = 'Population-weighted mean of base-canvas percent college-educated (% as 0-100).',
    cost_burden_pct_wavg = 'Population-weighted mean of base-canvas cost-burdened household share (% as 0-100).',
    rent_burden_pct_wavg = 'Population-weighted mean of base-canvas rent-burdened household share (% as 0-100).'
  )
);

-- SACOG Weighted Means — area-weighted averages for density/rate equity columns.
--
-- These columns (median_income, pct_minority, etc.) are density/rate measures
-- where raw SUM is meaningless. This model computes area-weighted averages:
-- SUM(col * pop) / SUM(pop).

WITH weighted AS (
    SELECT
        COALESCE(SUM(median_income * pop), 0) / NULLIF(SUM(pop), 0) AS median_income_wavg,
        COALESCE(SUM(pct_minority * pop), 0) / NULLIF(SUM(pop), 0) AS pct_minority_wavg,
        COALESCE(SUM(pct_college_educated * pop), 0) / NULLIF(SUM(pop), 0) AS pct_college_educated_wavg,
        COALESCE(SUM(cost_burden_pct * pop), 0) / NULLIF(SUM(pop), 0) AS cost_burden_pct_wavg,
        COALESCE(SUM(rent_burden_pct * pop), 0) / NULLIF(SUM(pop), 0) AS rent_burden_pct_wavg
    FROM brewgis.sacog.comparison
)
SELECT
    'brewgis'::text AS source,
    median_income_wavg,
    pct_minority_wavg,
    pct_college_educated_wavg,
    cost_burden_pct_wavg,
    rent_burden_pct_wavg
FROM weighted
