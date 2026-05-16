{#
    Allocation Apply Model

    Applies allocation weights to actual column values from the source
    table, producing a single allocated value per target row for a
    specific source column.

    For each target feature, the allocated value is:
        SUM(source_value * intersection_acres(source, target) / source_acres)
    summed across all intersecting source features.

    Inputs (via dbt vars):
        source_schema: Schema containing the source table
        source_table: Source table (e.g., census_block_groups)
        target_schema: Schema containing the target table
        target_table: Target table (e.g., parcels)
        source_column: Numeric column on source to allocate
        source_geom_col: Geometry column on source (default: geom)
        target_geom_col: Geometry column on target (default: geom)
        scenario_id: Unique identifier for this scenario run
#}

{{ config(materialized='view', alias='allocation_apply_' ~ var('scenario_id')) }}

WITH spatial_join AS (
    SELECT
        t.ctid AS target_ctid,
        s."{{ var('source_column') }}" AS source_value,
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
SELECT target_ctid, SUM(COALESCE(source_value, 0) * weight) AS allocated_value
FROM spatial_join
WHERE weight > 0
GROUP BY target_ctid
