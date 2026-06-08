MODEL (
  name brewgis.shared.allocation_factors,
  kind VIEW
);

-- Allocation Factors Model
--
-- Computes area-weighted allocation factors between a source layer
-- and a target layer. Each row represents a spatial overlap pair with
-- the fraction of the source geometry's area that falls within the
-- target geometry.
--
-- This is a parameterized model intended to be used with specific
-- source/target parameters. The generic version reads from the
-- configured source and target tables.

WITH source_wm AS (
    SELECT *, ST_Transform(geom, @VAR('wm_srid', 3857)) AS geom_wm
    FROM public.source_table
),
target_wm AS (
    SELECT *, ST_Transform(geom, @VAR('wm_srid', 3857)) AS geom_wm
    FROM public.target_table
),
spatial_join AS (
    SELECT
        s.__sid__ AS source_id,
        t.__tid__ AS target_id,
        @compute_allocation_weight(s, t, geom_wm, geom_wm) AS weight
    FROM source_wm s
    JOIN target_wm t
        ON ST_Intersects(s.geom_wm, t.geom_wm)
)
SELECT source_id, target_id, weight
FROM spatial_join
WHERE weight > 0
