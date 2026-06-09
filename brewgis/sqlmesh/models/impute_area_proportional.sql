MODEL (
  name brewgis.impute_area_proportional,
  kind VIEW,
  ignored_rules ["NoTransformInJoinWhere"]
);

-- Impute Area Proportional — spatial allocation imputation for target
-- features using area-proportional weights from intersecting source features.
--
-- For each target feature, the allocated value is:
--   SUM(source_value * intersection_acres(source, target) / source_acres)
--
-- This is a parameterized model. Customize source/target tables and columns
-- for specific use cases.

SELECT
    t.ctid AS target_ctid,
    COALESCE(
        t.target_column,
        sub.allocated_value
    ) AS imputed_value
FROM public.target_table t
LEFT JOIN (
    SELECT
        nt.ctid,
        SUM(
            COALESCE(s.source_column, 0)
            * @compute_allocation_weight(s, nt, geom, geom)
        ) AS allocated_value
    FROM (
        SELECT *, ST_Transform(geom, @VAR('wm_srid', 3857)) AS geom_wm
        FROM public.target_table
    ) nt
    JOIN (
        SELECT *, ST_Transform(geom, @VAR('wm_srid', 3857)) AS geom_wm
        FROM public.source_table
    ) s
        ON ST_Intersects(s.geom_wm, nt.geom_wm)
    WHERE nt.target_column IS NULL
      AND @compute_allocation_weight(s, nt, geom, geom) > 0
    GROUP BY nt.ctid
) sub ON t.ctid = sub.ctid
