MODEL (
  name brewgis.analysis.housing_cost_burden,
  kind FULL,
);

SELECT
    es.parcel_id,
    es.area_gross_acres,
    es.pop,
    es.hh,
    es.du,
    -- Cost-burdened households
    COALESCE(es.hh * @housing_cost_burden_rate, 0.0) AS cost_burdened_hh,
    -- Severely cost-burdened households
    COALESCE(es.hh * @housing_severe_burden_rate, 0.0) AS severely_cost_burdened_hh,
    -- Cost burden percentage
    COALESCE(
        (es.hh * @housing_cost_burden_rate) / NULLIF(es.hh, 0) * 100.0,
        0.0
    ) AS cost_burden_pct,
    -- Cost burden category
    CASE
        WHEN COALESCE(es.hh, 0) = 0 THEN 'low_burden'
        WHEN (es.hh * @housing_cost_burden_rate) / NULLIF(es.hh, 0) * 100.0 < 30.0
            THEN 'low_burden'
        WHEN (es.hh * @housing_cost_burden_rate) / NULLIF(es.hh, 0) * 100.0 <= 50.0
            THEN 'cost_burdened'
        ELSE 'severely_cost_burdened'
    END AS cost_burden_category,
    es.geometry
FROM brewgis.analysis.core_end_state AS es;


-- ------------------------------------------------------------
-- Displacement Risk / Gentrification Typology
--   Per-parcel displacement risk using Urban Displacement
--   Project (UDP) methodology: four equity indicators yield a
--   vulnerability score (0-4) mapped to risk categories.
-- Source (dbt): brewgis/dbt_project/models/displacement_risk.sql
-- ------------------------------------------------------------

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_housing_cost_burden_geometry_@snapshot_hash
  ON @this_model USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS idx_housing_cost_burden_parcel_id_@snapshot_hash
  ON @this_model USING btree (parcel_id);
ANALYZE @this_model;
