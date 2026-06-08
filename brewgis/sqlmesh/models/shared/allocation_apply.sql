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
        t.ctid AS target_ctid,
        s.source_column AS source_value,
        @compute_allocation_weight(s, t, geom_wm, geom_wm) AS weight
    FROM source_wm s
    JOIN target_wm t
        ON ST_Intersects(s.geom_wm, t.geom_wm)
)
SELECT target_ctid, SUM(COALESCE(source_value, 0) * weight) AS allocated_value
FROM spatial_join
WHERE weight > 0
GROUP BY target_ctid
