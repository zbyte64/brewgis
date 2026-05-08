{#
    Environmental Constraint Model

    Computes developable acres for each parcel by applying environmental
    constraint discounts in priority order. Overlapping constraint areas
    are unioned before discount calculation to prevent double-counting.

    The highest-priority constraint's discount_pct is applied to the
    full union of overlapping constraint geometries. Lower-priority
    constraint discount rates are ignored for overlapping areas (the
    highest-priority constraint "wins" for the shared area).

    Inputs (via dbt vars):
        source_schema: Schema containing source tables
        parcel_table: Table name for parcels (must have geom column)
        constraints: JSON list of constraint definitions [
            {"table": "floodplains", "geom_col": "geom", "discount_pct": 100},
            ...
        ]
        target_schema: Schema for output materialized view
        scenario_id: Unique identifier for this scenario run

    Output columns:
        parcel_id: Unique parcel identifier
        gross_acres: Total parcel area in acres
        acres_developable: Developable acres after constraint discounts
        developable_proportion: Ratio of developable to gross acres

    Materialized as: {{ var('target_schema') }}.env_constraint_{{ var('scenario_id') }}
#}

{{ config(alias='env_constraint_' ~ var('scenario_id')) }}
{%- set source_schema = var('source_schema') -%}
{%- set parcel_table = var('parcel_table') -%}
{%- set constraints = var('constraints') -%}

{%- if constraints %}

{#
    Build a CTE that unions ALL constraint geometries intersecting each
    parcel.  Overlapping constraints contribute their area only once to
    the union, preventing double-counting in the discount calculation.
#}
{%- set max_discount = constraints[0].discount_pct -%}
WITH constraint_union AS (
    SELECT
        p.id AS parcel_id,
        ST_Union(all_c.geom) AS constraint_geom
    FROM {{ source_schema }}.{{ parcel_table }} p
    JOIN (
        {%- for c in constraints %}
        {%- set geom_col = c.get('geom_col', 'geom') -%}
        {%- set tbl = c['table'] -%}
        SELECT {{ loop.index0 }} AS priority, {{ geom_col }} AS geom
        FROM {{ source_schema }}.{{ tbl }}
        {%- if not loop.last %} UNION ALL {% endif -%}
        {%- endfor %}
    ) all_c ON ST_Intersects(p.geom, all_c.geom)
    GROUP BY p.id
),
parcel_base AS (
    SELECT
        b.id AS parcel_id,
        ST_Area(b.geom) / 4046.86 AS gross_acres,
        b.geom,
        cu.constraint_geom
    FROM {{ source_schema }}.{{ parcel_table }} b
    LEFT JOIN constraint_union cu ON b.id = cu.parcel_id
)

SELECT
    parcel_base.parcel_id,
    parcel_base.gross_acres,
    CASE
        WHEN parcel_base.constraint_geom IS NOT NULL
        THEN GREATEST(0,
            parcel_base.gross_acres
            - (ST_Area(ST_Intersection(parcel_base.geom, parcel_base.constraint_geom)) / 4046.86)
              * {{ max_discount }} / 100.0
        )
        ELSE parcel_base.gross_acres
    END AS acres_developable,
    CASE
        WHEN parcel_base.gross_acres > 0
        THEN GREATEST(0,
            parcel_base.gross_acres
            - (ST_Area(ST_Intersection(parcel_base.geom, parcel_base.constraint_geom)) / 4046.86)
              * {{ max_discount }} / 100.0
        ) / parcel_base.gross_acres
        ELSE 0.0
    END AS developable_proportion,
    parcel_base.geom
FROM parcel_base

{%- else %}

{#
    No constraints — pass through gross acres as developable.
#}
    SELECT
        b.id AS parcel_id,
        1.0 AS developable_proportion,
        b.geom,
        ST_AREA(b.geom) / 4046.86 AS gross_acres,
        ST_AREA(b.geom) / 4046.86 AS acres_developable
    FROM {{ source_schema }}.{{ parcel_table }} AS b

{%- endif %}
