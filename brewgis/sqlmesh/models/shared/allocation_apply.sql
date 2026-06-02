MODEL (
  name brewgis.shared.allocation_apply,
  kind VIEW
);

-- Allocation Apply Model
--
-- Applies allocation weights to actual column values from the source
-- table, producing a single allocated value per target row for a
-- specific source column.
--
-- This is a parameterized model intended to be used with specific
-- source/target/column parameters. The generic version reads from
-- the configured allocation_factors view.

WITH spatial_join AS (
    SELECT
        t.ctid AS target_ctid,
        s.source_column AS source_value,
        @compute_allocation_weight(s, t, geom, geom) AS weight
    FROM public.source_table s
    JOIN public.target_table t
        ON ST_Intersects(
            ST_Transform(s.geom, 3857),
            ST_Transform(t.geom, 3857)
        )
)
SELECT target_ctid, SUM(COALESCE(source_value, 0) * weight) AS allocated_value
FROM spatial_join
WHERE weight > 0
GROUP BY target_ctid
