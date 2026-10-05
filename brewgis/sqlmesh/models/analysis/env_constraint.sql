MODEL (
  name brewgis.@{scenario_schema}.@{model_table},
  kind FULL,
  description 'Per-parcel environmental constraint coverage: acres overlapped by each constraint layer discounted to a developable-area reduction.',
  column_descriptions (
    parcel_id = 'Assessor parcel number (APN) of the parcel.',
    geometry = 'Parcel boundary geometry (EPSG:4326).',
    area_gross_acres = 'Gross parcel area (acres).',
    constraint_acres = 'Parcel acres excluded from development by the scenario''s constraint layers (overlapping layers counted once), each discounted by its configured share and capped at the gross area (acres).',
    acres_developable = 'Gross area less the constraint acres: the acreage a scenario may develop (acres).',
    developable_proportion = 'Developable share of the gross area (0-1); zero without area.'
  ),
  blueprints @analysis_blueprints('env_constraint'),
  audits (
    not_null(columns := (parcel_id,)),
    unique_values(columns := (parcel_id,)),
    assert_column_non_negative(column_name := constraint_acres),
    assert_column_non_negative(column_name := acres_developable)
  )
);

-- Environmental constraint — the acreage each parcel loses to constrained land.
--
-- Reads the scenario's own constraint configuration (``Scenario.constraints``,
-- ``[{table, discount_pct, geom_col}]``) and reports, per parcel, the part of
-- it covered by the configured constraint layers, each discounted by that
-- layer's share. ``acres_developable`` is the gross area less that coverage —
-- the acreage the allocation step may build on.
--
-- It runs against whatever parcels the scenario's canvas holds, so a *base*
-- scenario reports the existing constrained acreage (streams and wetlands do
-- not stop being constraints because the year is 2012) while an *alternative*
-- scenario's end state is what its allocation discounts. UrbanFootprint's
-- ``environmental_constraint_updater_tool.py`` behaves the same way; its
-- exported ``_base`` columns are zero only because its tool is scenario-scoped.
--
-- Walk-through of the run: env_constraint runs before core, and
-- ``core_end_state`` reads this model's ``acres_developable``, so a scenario's
-- end state already reflects the constraint discount. A scenario with no
-- constraints configured exports an empty constraint relation (see the macro),
-- which leaves every parcel whole.
--
-- Shape, and why it looks the way it does:
--
--   * The constraint polygons are the *outer* side of an index nested loop, and
--     the parcels are probed through a ``JOIN LATERAL`` against the canvas's own
--     GiST index. That is not a stylistic choice: the mirrored join order
--     (parcels outer, constraint relation materialised inner) makes the planner
--     evaluate ``ST_Intersects`` as a join filter over 52,187 x 39,571 pairs,
--     which measured 240 s on the SACOG canvas against 0.9 s for this shape.
--   * A parcel-side ``@ref_model(@parcel_table)`` CTE cannot be used inside the
--     lateral: Postgres materialises a CTE referenced more than once, and a
--     materialised CTE has no index to probe. The lateral therefore reads the
--     parcel table directly, and the final projection reads it again.
--   * Overlaps are tested in EPSG:4326 (``probe_geom``, the canvas's own CRS, so
--     the predicate is index-driven) and *measured* in the region's
--     ``local_srid`` (``local_geom``): a geographic CRS has no planar area.
--   * The pieces are **unioned per (parcel, discount)**, so land covered by two
--     constraint layers is counted once: a parcel cannot lose more acres than
--     it has. Summing the raw intersections instead double-counts every
--     cross-layer overlap — on the SACOG canvas that reported 40 parcels
--     losing more acreage than they own, the worst by 3.3 acres. Layers with
--     different discounts are unioned in their own group (the configuration
--     carries no priority between layers), and the total is capped at the gross
--     area for the same reason.
--   * Constraint slivers below ``@constraint_min_overlap_sqm()`` m2 are dropped
--     before the union. They are boundary noise, not constraints: on the SACOG
--     canvas the raw intersections flag 2,153 parcels, and 1,046 of them
--     overlap by less than 5 m2 while contributing 0.05 acres in total.

WITH hits AS (
    SELECT
        h.parcel_id,
        q.discount_pct,
        ST_Area(ST_Union(h.piece_local)) AS overlap_sqm
    FROM @constraint_geometries(@blueprint_var('constraints')) AS q
    JOIN LATERAL (
        SELECT
            p.parcel_id,
            ST_Intersection(q.local_geom, ST_Transform(p.geometry, @local_srid()))
                AS piece_local
        FROM @ref_model(@parcel_table) AS p
        WHERE ST_Intersects(q.probe_geom, p.geometry)
    ) AS h ON TRUE
    WHERE ST_Area(h.piece_local) > @constraint_min_overlap_sqm()
    GROUP BY h.parcel_id, q.discount_pct
),

constraint_overlap AS (
    SELECT
        parcel_id,
        SUM(public.sqm_to_acres(overlap_sqm) * discount_pct / 100.0)
            AS constraint_acres
    FROM hits
    GROUP BY parcel_id
)

SELECT
    parcel_id,
    geometry,
    area_gross_acres,
    LEAST(constraint_acres, area_gross_acres) AS constraint_acres,
    area_gross_acres - LEAST(constraint_acres, area_gross_acres) AS acres_developable,
    CASE
        WHEN area_gross_acres > 0
        THEN (area_gross_acres - LEAST(constraint_acres, area_gross_acres))
            / area_gross_acres
        ELSE 0.0
    END AS developable_proportion
FROM (
    SELECT
        p.parcel_id,
        p.geometry,
        @st_area_projected(p.geometry) AS area_gross_acres,
        COALESCE(o.constraint_acres, 0.0) AS constraint_acres
    FROM @ref_model(@parcel_table) AS p
    LEFT JOIN constraint_overlap AS o
        ON o.parcel_id = p.parcel_id
) AS combined;

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_env_constraint_geometry_')
  ON @this_model USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_env_constraint_parcel_id_')
  ON @this_model USING btree (parcel_id);
ANALYZE @this_model;


-- Publish this model's result view where the Layers, Martin and UI paths read
-- it. The view selects from this model's prod virtual view (never its physical
-- table), so promoting a non-prod environment never repoints it. See
-- sqlmesh/macros/analysis_blueprints.py.
ON_VIRTUAL_UPDATE_BEGIN;

CREATE SCHEMA IF NOT EXISTS "@{result_schema}";

CREATE OR REPLACE VIEW "@{result_schema}"."@{model_table}" AS
SELECT * FROM @{scenario_schema}."@{model_table}";

ON_VIRTUAL_UPDATE_END;
