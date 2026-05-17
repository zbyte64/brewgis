{#
    SACOG Weighted Means — area-weighted averages for density/rate equity columns.

    These columns (median_income, pct_minority, etc.) are density/rate measures
    where raw SUM is meaningless. This model computes area-weighted averages:
    SUM(col * pop) / SUM(pop).

    Vars:
        comparison_brewgis_table: BrewGIS base canvas table name.

    Materialized as: table (persisted for report generation)
#}
{{ config(materialized='table') }}

{% set brew_table = var('comparison_brewgis_table', 'public.base_canvas') %}

WITH weighted AS (
    SELECT
        COALESCE(SUM("median_income" * "pop"), 0) / NULLIF(SUM("pop"), 0) AS median_income_wavg,
        COALESCE(SUM("pct_minority" * "pop"), 0) / NULLIF(SUM("pop"), 0) AS pct_minority_wavg,
        COALESCE(SUM("pct_college_educated" * "pop"), 0) / NULLIF(SUM("pop"), 0) AS pct_college_educated_wavg,
        COALESCE(SUM("cost_burden_pct" * "pop"), 0) / NULLIF(SUM("pop"), 0) AS cost_burden_pct_wavg,
        COALESCE(SUM("rent_burden_pct" * "pop"), 0) / NULLIF(SUM("pop"), 0) AS rent_burden_pct_wavg
    FROM {{ brew_table }}
)
SELECT
    'brewgis'::text AS source,
    median_income_wavg,
    pct_minority_wavg,
    pct_college_educated_wavg,
    cost_burden_pct_wavg,
    rent_burden_pct_wavg
FROM weighted
