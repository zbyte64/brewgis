MODEL (
  name brewgis.analysis.stormwater_runoff,
  kind FULL,
);

WITH land_data AS (
    SELECT
        lc.parcel_id,
        lc.gross_acres,
        lc.impervious_acres,
        lc.impervious_pct,
        es.geom,
        0.0::double precision AS impervious_acres_baseline
        -- Note: impervious-acres increment not yet modeled in core_increment;
        -- baseline defaults to 0, making pct_baseline = pct below
    FROM brewgis.analysis.land_consumption AS lc
    LEFT JOIN brewgis.analysis.core_end_state AS es
        ON lc.parcel_id = es.parcel_id
),

-- Compute baseline impervious percentage from increment delta
baseline AS (
    SELECT
        parcel_id,
        gross_acres,
        impervious_acres,
        impervious_pct,
        geom,
        GREATEST(
            impervious_pct
            - CASE
                WHEN gross_acres > 0
                    THEN impervious_acres_baseline / gross_acres * 100.0
                ELSE 0.0
            END,
            0.0
        ) AS impervious_pct_baseline
    FROM land_data
),

-- Compute runoff volumes
runoff AS (
    SELECT
        parcel_id,
        impervious_acres,
        impervious_pct,
        geom,
        0.05 + 0.009 * impervious_pct AS runoff_coefficient,
        @stormwater_annual_precipitation_in * 0.9
        * (0.05 + 0.009 * impervious_pct)
        * gross_acres / 12.0 AS runoff_volume_acre_ft,
        0.05 + 0.009 * impervious_pct_baseline AS runoff_coefficient_baseline,
        @stormwater_annual_precipitation_in * 0.9
        * (0.05 + 0.009 * impervious_pct_baseline)
        * gross_acres / 12.0 AS runoff_baseline_acre_ft
    FROM baseline
)

SELECT
    parcel_id,
    impervious_acres,
    impervious_pct,
    runoff_coefficient,
    runoff_volume_acre_ft,
    runoff_baseline_acre_ft,
    geom,
    runoff_volume_acre_ft - runoff_baseline_acre_ft AS runoff_change_acre_ft,
    CASE
        WHEN runoff_baseline_acre_ft > 0
            THEN
                (runoff_volume_acre_ft - runoff_baseline_acre_ft)
                / runoff_baseline_acre_ft * 100.0
        ELSE 0.0
    END AS runoff_change_pct
FROM runoff;


-- ------------------------------------------------------------
-- Tree Canopy / Urban Heat Island
--   Parcel-level tree canopy cover percentage and surface
--   temperature proxy using published urban heat island
--   relationships (~1F reduction per 10% canopy increase).
-- Source (dbt): brewgis/dbt_project/models/tree_canopy.sql
-- ------------------------------------------------------------

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_stormwater_runoff_geom
  ON brewgis.analysis.stormwater_runoff USING GIST (geom);
  CREATE INDEX IF NOT EXISTS idx_stormwater_runoff_parcel_id
  ON brewgis.analysis.stormwater_runoff (parcel_id);
ANALYZE brewgis.analysis.stormwater_runoff;
