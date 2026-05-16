{{ config(
    materialized='view',
    alias='impute_area_proportional_' ~ var('scenario_id')
) }}

SELECT
    t.ctid AS target_ctid,
    COALESCE(
        t.{{ var('target_column') }},
        sub.allocated_value
    ) AS imputed_value
FROM {{ var('target_schema') }}.{{ var('target_table') }} t
LEFT JOIN (
    SELECT
        nt.ctid,
        SUM(
            COALESCE(s.{{ var('source_column') }}, 0)
            * {{ compute_allocation_weight(
                's', 'nt',
                var('source_geom_col', 'geom'),
                var('target_geom_col', 'geom')
            ) }}
        ) AS allocated_value
    FROM {{ var('target_schema') }}.{{ var('target_table') }} nt
    JOIN {{ var('source_schema') }}.{{ var('source_table') }} s
        ON ST_Intersects(
            ST_Transform(s.{{ var('source_geom_col', 'geom') }}, 3857),
            ST_Transform(nt.{{ var('target_geom_col', 'geom') }}, 3857)
        )
    WHERE nt.{{ var('target_column') }} IS NULL
      AND {{ compute_allocation_weight(
          's', 'nt',
          var('source_geom_col', 'geom'),
          var('target_geom_col', 'geom')
      ) }} > 0
    GROUP BY nt.ctid
) sub ON t.ctid = sub.ctid
