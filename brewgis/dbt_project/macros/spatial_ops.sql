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
            SELECT SUM(ST_Area(ST_Intersection(p.geom, c.{{ geom_col }}))) / 4046.86
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
    GREATEST(
        0,
        {{ acres_before_expr }}
        - (
            COALESCE(
                (
                    SELECT SUM(ST_Area(ST_Intersection(p.geom, c.{{ geom_col }}))) / 4046.86
                    FROM {{ schema }}.{{ table_name }} c
                    WHERE ST_Intersects(p.geom, c.{{ geom_col }})
                ),
                0.0
            ) * {{ discount_pct }} / 100.0
        )
    )
{% endmacro %}
