{#
    SACOG Parcel Column Shim — maps SACOG v1 columns to brewgis-standard column names.

    Reads raw SACOG parcel data from ``public.sacog_comparison_parcels`` (populated
    by the compare_sacog_basemap management command) and produces a table with
    brewgis-compatible column names so that ``base_canvas_geometry`` and the rest of
    the base_canvas chain can consume SACOG v1 data without column-name failures.

    Column mapping:
        parcel_id            → geography_id (via Phase1 normalization)
        geometry             → geometry (PostGIS MultiPolygon, 4326)
        county               → 'Sacramento' (constant — all parcels in Sacramento County)
        land_development_category → NULL (let base_canvas_attributes classify from land_use/assessor_use_code)
        built_form_key       → NULL (let base_canvas_attributes set default 'mixed_use')
        intersection_density → NULL (let base_canvas_imputed fill)
        pop                  → NULL (let base_canvas_demographics fill from ACS)
        hh                   → NULL (let base_canvas_demographics fill from ACS)
        du                   → du (direct pass-through)
        emp                  → emp (direct pass-through)
        land_use             → land_use (pass-through — needed by base_canvas_attributes)
        assessor_use_code    → assessor (rename — needed by base_canvas_attributes)

    Other pass-through columns from SACOG v1:
        acres, ret, off, pub, ind, other, jurisdiction, gp, gluc,
        census_blockgroup, census_block, notes

    Materialized as: table
#}

{{ config(materialized='table') }}

SELECT
    parcel_id,
    geometry,
    'Sacramento'::text AS county,
    NULL::text AS land_development_category,
    NULL::text AS built_form_key,
    NULL::double precision AS intersection_density,
    NULL::double precision AS pop,
    NULL::double precision AS hh,
    du,
    emp,
    land_use,
    assessor AS assessor_use_code,
    acres,
    ret,
    off,
    pub,
    ind,
    other,
    jurisdiction,
    gp,
    gluc,
    census_blockgroup,
    census_block,
    notes
FROM public.sacog_comparison_parcels
