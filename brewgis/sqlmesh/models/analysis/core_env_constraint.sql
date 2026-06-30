MODEL (
  name brewgis.analysis.env_constraint,
  kind FULL,
  audits (
    not_null(columns := (parcel_id)),
    number_of_rows(threshold := 1)
  )
);

-- Environmental Constraint Model
-- Computes developable acres for each parcel by applying environmental
-- constraint discounts. Overlapping constraint geometries are unioned
-- before discount calculation to prevent double-counting.
--
-- The highest-priority constraint's discount_pct is applied to the
-- full union of overlapping constraint geometries.
--
-- Input variables:
--   @parcel_table:  Table containing parcel geometries (must have id, geom)
--   @constraint_table: Unified table with constraint_type, geom columns
--   @constraints:   JSON array of {type, discount_pct} objects, ordered
--                   by priority (first = highest)
--
-- Output columns:
--   parcel_id, gross_acres, acres_developable,
--   developable_proportion, geom

WITH constraint_types AS (
    SELECT
        (@constraints::json -> 0 ->> 'discount_pct')::numeric AS max_discount
),
constraint_union AS (
    SELECT
        p.id AS parcel_id,
        ST_Union(ct.geom) AS constraint_geom
    FROM @parcel_table AS p
    JOIN @constraint_table AS ct
        ON ST_Intersects(p.geom, ct.geom)
    JOIN json_array_elements(@constraints::json) AS c
        ON ct.constraint_type = c->>'type'
    GROUP BY p.id
)
SELECT
    b.id AS parcel_id,
    @st_area_projected(b.geom) AS gross_acres,
    CASE
        WHEN cu.constraint_geom IS NOT NULL
        THEN GREATEST(0,
            @st_area_projected(b.geom)
            - public.intersection_acres(
                ST_Transform(b.geom, @VAR('local_srid', 3310)),
                ST_Transform(cu.constraint_geom, @VAR('local_srid', 3310))
              ) * cd.max_discount / 100.0
        )
        ELSE @st_area_projected(b.geom)
    END AS acres_developable,
    CASE
        WHEN @st_area_projected(b.geom) > 0
        THEN GREATEST(0,
            @st_area_projected(b.geom)
            - public.intersection_acres(
                ST_Transform(b.geom, @VAR('local_srid', 3310)),
                ST_Transform(cu.constraint_geom, @VAR('local_srid', 3310))
              ) * cd.max_discount / 100.0
        ) / NULLIF(@st_area_projected(b.geom), 0)
        ELSE 0.0
    END AS developable_proportion,
    b.geom
FROM @parcel_table AS b
LEFT JOIN constraint_union AS cu ON b.id = cu.parcel_id
CROSS JOIN constraint_types AS cd;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_env_constraint_geom_@snapshot_hash
  ON @this_model USING GIST (geom);

  CREATE INDEX IF NOT EXISTS idx_env_constraint_parcel_id_@snapshot_hash
  ON @this_model USING btree (parcel_id);
