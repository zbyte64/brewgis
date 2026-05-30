{#
    SACOG Comparison Dasymetric Crosswalk — area-weighted assessor → SACOG parcel mapping.

    Joins SACOG parcel geometries (sacog_parcel_shim) against assessor-derived
    dasymetric weights (parcel_dasymetric_weights) using ST_Intersects and picks
    the best match per SACOG parcel_id by largest intersection area.

    The geometry on both sides is already ST_MakeValid'd (validated in the source
    materializations), so no on-the-fly ST_MakeValid is needed here — this model
    can use a plain ST_Intersects that hits the spatial index.

    Materialized as: table
        - Unique index on parcel_id (one row per SACOG parcel)
        - GIST index on geometry for downstream spatial queries
#}

{{ config(materialized='table',
    indexes=[
        {'columns': ['parcel_id'], 'unique': True},
        {'columns': ['geometry'], 'type': 'gist'},
    ])
}}

SELECT DISTINCT ON (sp.parcel_id)
    sp.parcel_id,
    dw.lot_size_acres,
    dw.land_development_category,
    dw.actual_living_sqft,
    dw.actual_building_sqft,
    dw.estimated_living_sqft,
    dw.estimated_building_sqft,
    dw.impervious_fraction,
    dw.intersection_density,
    dw.pop_dasym_weight,
    dw.emp_dasym_weight,
    dw.du_subtype,
    dw.du_dasym_weight,
    sp.geometry
FROM {{ ref('sacog_parcel_shim') }} sp
JOIN {{ ref('parcel_dasymetric_weights') }} dw
    ON ST_Intersects(sp.geometry, dw.geometry)
ORDER BY sp.parcel_id, ST_Area(ST_Intersection(sp.geometry, dw.geometry)) DESC
