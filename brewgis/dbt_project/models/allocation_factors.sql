{#
    Allocation Factors Model

    Computes area-weighted allocation factors between a source layer
    (e.g., census block groups) and a target layer (e.g., parcels).
    Each row represents a spatial overlap pair with the fraction of
    the source geometry's area that falls within the target geometry.

    The weight is computed as:
        intersection_acres(source, target) / source_acres

    Values are in [0, 1], with 0 indicating no overlap (filtered out).

    The canonical expression matches the `compute_allocation_weight` macro
    defined in macros/spatial_ops.sql.

    Inputs (via dbt vars):
        source_schema: Schema containing the source table
        source_table: Source table (e.g., census_block_groups)
        target_schema: Schema containing the target table
        target_table: Target table (e.g., parcels)
        source_id_col: ID column on source (default: __sid__)
        target_id_col: ID column on target (default: __tid__)
        source_geom_col: Geometry column on source (default: geom)
        target_geom_col: Geometry column on target (default: geom)
        scenario_id: Unique identifier for this scenario run
#}

{{ config(materialized='view', alias='allocation_factors_' ~ var('scenario_id')) }}

WITH spatial_join AS (
    SELECT
        s."{{ var('source_id_col', '__sid__') }}" AS source_id,
        t."{{ var('target_id_col', '__tid__') }}" AS target_id,
        {{ compute_allocation_weight(
            's', 't',
            var('source_geom_col', 'geom'),
            var('target_geom_col', 'geom')
        ) }} AS weight
    FROM {{ var('source_schema') }}."{{ var('source_table') }}" s
    JOIN {{ var('target_schema') }}."{{ var('target_table') }}" t
        ON ST_Intersects(
            ST_Transform(s."{{ var('source_geom_col', 'geom') }}", 3857),
            ST_Transform(t."{{ var('target_geom_col', 'geom') }}", 3857)
        )
)
SELECT source_id, target_id, weight
FROM spatial_join
WHERE weight > 0
