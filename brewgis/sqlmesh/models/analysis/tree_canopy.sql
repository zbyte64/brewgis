MODEL (
  name brewgis.analysis.tree_canopy,
  kind FULL,
);

WITH parcel_canopy AS (
    SELECT
        es.parcel_id,
        es.gross_acres,
        es.population,
        es.households,
        es.geom,
        -- Canopy cover: estimate from land use category
        CASE
            WHEN es.land_dev_category = 'compact' THEN 25.0  -- dense urban (low canopy)
            WHEN es.land_dev_category = 'urban' THEN 15.0
            WHEN es.land_dev_category = 'standard' THEN 30.0  -- suburban (moderate)
            WHEN es.land_dev_category = 'rural' THEN 45.0     -- rural (high canopy)
            ELSE 20.0
        END AS canopy_pct
    FROM brewgis.analysis.core_end_state AS es
)
SELECT
    parcel_id,
    gross_acres,
    population,
    households,
    canopy_pct,
    -- Surface temp proxy: baseline minus cooling effect
    ROUND((@tree_canopy_baseline_temp - (canopy_pct / 10.0 * @tree_canopy_temp_per_10pct))::numeric, 1) AS surface_temp_f,
    -- Heat exposure score: 0-100 (higher = worse, inverse of canopy)
    ROUND(GREATEST(0.0, 100.0 - (canopy_pct * 4.0))::numeric, 1) AS heat_exposure_score,
    geom
FROM parcel_canopy;


-- ------------------------------------------------------------
-- Food Access (H3 — mRFEI)
--   Modified Retail Food Environment Index (mRFEI) per parcel
--   using OSM Points of Interest data.
-- Source (dbt): brewgis/dbt_project/models/food_access.sql
-- ------------------------------------------------------------
