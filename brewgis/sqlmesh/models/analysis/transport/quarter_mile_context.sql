MODEL (
  name brewgis.@{scenario_schema}.@{model_table},
  kind FULL,
  description 'Per-parcel quarter-mile buffer context: population, employment and residential / employment / mixed acreage within 403 m, plus employment within 1609 m.',
  column_descriptions (
    parcel_id = 'Parcel identifier from the scenario end state (core_end_state).',
    qmb_pop = 'Population summed over every parcel centroid within 403 m of this parcel centroid (people).',
    qmb_emp = 'Employment summed over every parcel centroid within 403 m of this parcel centroid (jobs).',
    qmb_res_acres = 'Developed acres of residential parcels (dwelling units > 0) whose centroid lies within 403 m (acres).',
    qmb_emp_acres = 'Developed acres of employment parcels (jobs > 0) whose centroid lies within 403 m (acres).',
    qmb_mixed_acres = 'Developed acres of mixed-use parcels (dwelling units > 0 and jobs > 0) whose centroid lies within 403 m (acres).',
    emp_1mile = 'Employment summed over every parcel centroid within 1609 m of this parcel centroid (jobs).'
  ),
  blueprints @analysis_blueprints('quarter_mile_context'),
  audits (
    not_null(columns := (parcel_id,)),
    unique_values(columns := (parcel_id,))
  )
);

-- Quarter-mile context — the buffer-aggregated density, mix and accessibility
-- terms mode_choice's hierarchical sigmoid reads (UrbanFootprint's qmb_* and
-- emp_within_1mile columns, vmt_calculate_log_odds.py).
--
-- Not an analysis module: it has no MODULE_RESULT_TABLES /
-- MODULE_SQLMESH_SELECTORS entry and publishes no result view — it is a support
-- model of mode_choice, instantiated per analyzed scenario like every other
-- blueprinted analysis model (the same shape network_zone_distance has for
-- trip_distribution).
--
-- The join is on centroid_local, the projected, GiST-indexed point
-- core_end_state carries, and the radius is expressed in the region's local
-- unit (see the AGENTS local-unit rule): a constant radius in the indexed
-- column's own CRS is what lets the planner use the index.
--
-- Every parcel gets a row: the aggregate on the left is what a parcel with
-- NULL (or missing) geometry has none of, and the LEFT JOINs keep it in the
-- result with zero context instead of dropping it — mode_choice must emit a
-- row for every parcel trip_generation priced.

WITH derived AS (
    SELECT
        es.parcel_id,
        es.centroid_local,
        COALESCE(es.pop, 0.0) AS pop,
        COALESCE(es.emp, 0.0) AS emp,
        CASE
            WHEN COALESCE(es.du, 0.0) > 0
            THEN COALESCE(es.parcel_acres_developed, 0.0)
            ELSE 0.0
        END AS res_acres,
        CASE
            WHEN COALESCE(es.emp, 0.0) > 0
            THEN COALESCE(es.parcel_acres_developed, 0.0)
            ELSE 0.0
        END AS emp_acres,
        CASE
            WHEN COALESCE(es.du, 0.0) > 0 AND COALESCE(es.emp, 0.0) > 0
            THEN COALESCE(es.parcel_acres_developed, 0.0)
            ELSE 0.0
        END AS mixed_acres
    FROM @{scenario_schema}.core_end_state AS es
),

quarter_mile AS (
    SELECT
        a.parcel_id,
        SUM(b.pop) AS qmb_pop,
        SUM(b.emp) AS qmb_emp,
        SUM(b.res_acres) AS qmb_res_acres,
        SUM(b.emp_acres) AS qmb_emp_acres,
        SUM(b.mixed_acres) AS qmb_mixed_acres
    FROM derived AS a
    JOIN derived AS b
        ON ST_DWithin(a.centroid_local, b.centroid_local, @metres_in_local_units(403.0))
    GROUP BY a.parcel_id
),

one_mile AS (
    SELECT
        a.parcel_id,
        SUM(b.emp) AS emp_1mile
    FROM derived AS a
    JOIN derived AS b
        ON ST_DWithin(a.centroid_local, b.centroid_local, @metres_in_local_units(1609.0))
    GROUP BY a.parcel_id
)

SELECT
    d.parcel_id,
    COALESCE(q.qmb_pop, 0.0) AS qmb_pop,
    COALESCE(q.qmb_emp, 0.0) AS qmb_emp,
    COALESCE(q.qmb_res_acres, 0.0) AS qmb_res_acres,
    COALESCE(q.qmb_emp_acres, 0.0) AS qmb_emp_acres,
    COALESCE(q.qmb_mixed_acres, 0.0) AS qmb_mixed_acres,
    COALESCE(m.emp_1mile, 0.0) AS emp_1mile
FROM derived AS d
LEFT JOIN quarter_mile AS q ON q.parcel_id = d.parcel_id
LEFT JOIN one_mile AS m ON m.parcel_id = d.parcel_id
ORDER BY d.parcel_id;

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_quarter_mile_context_parcel_id_')
  ON @this_model USING btree (parcel_id);
ANALYZE @this_model;
