{#
    SACOG Parcel Column Shim — maps SACOG v1 columns to brewgis-standard column names.

    Reads raw SACOG parcel data from ``{{ var('comparison_parcel_table', 'public.sacog_comparison_parcels') }}`` (populated
    by the compare_sacog_basemap management command) and produces a table with
    brewgis-compatible column names so that ``base_canvas_geometry`` and the rest of
    the base_canvas chain can consume SACOG v1 data without column-name failures.

    Column mapping:
        parcel_id            → geography_id (via Phase1 normalization)
        geometry             → ST_Transform(SACOG CA Albers → 4326)
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

{{ config(materialized='table',
    indexes=[
        {'columns': ['geometry'], 'type': 'gist'},
        {'columns': ['local_geometry'], 'type': 'gist'},
        {'columns': ['parcel_id'], 'unique': True},
    ])
}}

SELECT
    parcel_id,
    ST_MakeValid(ST_Transform(geometry, 4326)) AS geometry,
    ST_MakeValid(geometry) AS local_geometry,
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
    notes,
    NULL::double precision AS bldg_area_detsf_sl,
    NULL::double precision AS bldg_area_detsf_ll,
    NULL::double precision AS bldg_area_attsf,
    NULL::double precision AS bldg_area_mf,
    NULL::double precision AS bldg_area_retail_services,
    NULL::double precision AS bldg_area_restaurant,
    NULL::double precision AS bldg_area_accommodation,
    NULL::double precision AS bldg_area_arts_entertainment,
    NULL::double precision AS bldg_area_other_services,
    NULL::double precision AS bldg_area_office_services,
    NULL::double precision AS bldg_area_public_admin,
    NULL::double precision AS bldg_area_education,
    NULL::double precision AS bldg_area_medical_services,
    NULL::double precision AS bldg_area_transport_warehousing,
    NULL::double precision AS bldg_area_wholesale,
    NULL::double precision AS residential_irrigated_area,
    NULL::double precision AS commercial_irrigated_area,
    NULL::double precision AS area_parcel_res,
    NULL::double precision AS area_parcel_emp_ag,
    NULL::double precision AS area_parcel_emp,
    NULL::double precision AS area_parcel_mixed_use,
    NULL::double precision AS area_parcel_no_use
FROM {{ var('comparison_parcel_table', 'public.sacog_comparison_parcels') }}
