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

WITH spatial_join AS (
    SELECT
        s.__sid__ AS source_id,
        t.__tid__ AS target_id,
        @compute_allocation_weight(s, t, geom, geom) AS weight
    FROM public.source_table s
    JOIN public.target_table t
        ON ST_Intersects(
            ST_Transform(s.geom, 3857),
            ST_Transform(t.geom, 3857)
        )
)
SELECT source_id, target_id, weight
FROM spatial_join
WHERE weight > 0
