{# -*- mode: jinja -*- #}
{# Spatial operation macros for environmental constraint analysis. #}


{#
    Compute the overlap area in acres between a parcel and a constraint layer.

    Returns a SQL expression (scalar subquery) that computes the total
    intersection area in acres. 4046.86 sqm = 1 acre.

    Usage::
        {{ constraint_acres("floodplains", "geom") }}
        {{ constraint_acres("wetlands", "geom", .schema) }}
#}
{% macro constraint_acres(table_name, geom_col="geom", schema=var("source_schema")) %}
    COALESCE(
        (
            SELECT SUM(public.intersection_acres(p.geom, c.{{ geom_col }}))
            FROM {{ schema }}.{{ table_name }} c
            WHERE ST_Intersects(p.geom, c.{{ geom_col }})
        ),
        0.0
    )
{% endmacro %}


{#
    Compute the developable acres after applying a constraint discount.

    Returns a SQL expression:

        GREATEST(0, acres_before - overlap_acres * discount_pct / 100.0)

    Where overlap_acres is the area of intersection between parcel and constraint
    layer, and discount_pct is the percentage of that area to count against
    developable acreage (e.g., 100 for total loss, 50 for partial).
#}
{% macro apply_constraint(acres_before_expr, table_name, geom_col, discount_pct, schema=var("source_schema")) %}
    public.clamp_non_negative(
        {{ acres_before_expr }}
        - (
            COALESCE(
                (
                    SELECT SUM(public.intersection_acres(p.geom, c.{{ geom_col }}))
                    FROM {{ schema }}.{{ table_name }} c
                    WHERE ST_Intersects(p.geom, c.{{ geom_col }})
                ),
                0.0
            ) * {{ discount_pct }} / 100.0
        )
    )
{% endmacro %}


{#
    Compute the area-weighted allocation factor between source and target geometries.

    Returns a SQL expression producing the ratio of intersection area to source
    area — i.e., the fraction of each source geometry's area that overlaps a target
    geometry. Both geometries are projected to SRID 3857 for area measurement.
    The 4046.86 acre-conversion factor cancels out in the division, so the result
    is a pure ratio in [0, 1].

    Usage:
        SELECT {{ compute_allocation_weight('s', 't', 'geom', 'geom') }} AS weight
        FROM source_table s
        JOIN target_table t ON ST_Intersects(ST_Transform(s.geom, 3857), ST_Transform(t.geom, 3857))
#}
{% macro compute_allocation_weight(source_alias, target_alias, source_geom='geom', target_geom='geom') %}
    public.intersection_acres(
        ST_Transform({{ source_alias }}.{{ source_geom }}, 3857),
        ST_Transform({{ target_alias }}.{{ target_geom }}, 3857)
    ) / NULLIF(public.acres(ST_Transform({{ source_alias }}.{{ source_geom }}, 3857)), 0)
{% endmacro %}
