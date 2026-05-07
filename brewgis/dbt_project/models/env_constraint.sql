{#
    Environmental Constraint Model

    Computes developable acres for each parcel by applying environmental
    constraint discounts in priority order. Higher-priority constraints
    (lower index) are applied first and consume their full discount.
    Lower-priority constraints only discount area not already consumed.

    Inputs (via dbt vars):
        source_schema: Schema containing source tables
        parcel_table: Table name for parcels (must have geom, gross_acres columns)
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

{%- set source_schema = var('source_schema') -%}
{%- set parcel_table = var('parcel_table') -%}
{%- set constraints = var('constraints') -%}

{#
    Build a chain of constraint discounts.

    For each constraint in priority order, we compute:
        remaining_after = GREATEST(0, remaining_before - overlap_acres * discount_pct / 100)

    This is implemented as a chain of COALESCE/GREATEST expressions.
#}
{%- macro build_constraint_chain() %}
    {%- set parcel_acres = "ST_Area(p.geom) / 4046.86" -%}
    {%- set expr = parcel_acres -%}
    {%- for c in constraints %}
        {%- set geom_col = c.get('geom_col', 'geom') -%}
        {%- set discount = c['discount_pct'] -%}
        {%- set tbl = c['table'] -%}
        {%- set overlap = "COALESCE((SELECT SUM(ST_Area(ST_Intersection(p.geom, c_%d.%s))) / 4046.86 FROM %s.%s c_%d WHERE ST_Intersects(p.geom, c_%d.%s)), 0.0)" | format(loop.index, geom_col, source_schema, tbl, loop.index, loop.index, geom_col) -%}
        {%- set expr = "GREATEST(0, %s - %s * %s / 100.0)" | format(expr, overlap, discount) -%}
    {%- endfor -%}
    {{ expr }}
{%- endmacro -%}

WITH parcel_base AS (
    SELECT
        {{ parcel_table }}.id AS parcel_id,
        ST_Area({{ parcel_table }}.geom) / 4046.86 AS gross_acres,
        {{ parcel_table }}.geom
    FROM {{ source_schema }}.{{ parcel_table }}
)

SELECT
    parcel_base.parcel_id,
    parcel_base.gross_acres,
    {{ build_constraint_chain() }} AS acres_developable,
    CASE
        WHEN parcel_base.gross_acres > 0
        THEN {{ build_constraint_chain() }} / parcel_base.gross_acres
        ELSE 0.0
    END AS developable_proportion,
    parcel_base.geom
FROM parcel_base
