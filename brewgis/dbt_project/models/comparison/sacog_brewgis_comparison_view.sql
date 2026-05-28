{#
    SACOG BrewGIS Comparison View — wraps base_canvas_reconciled with geography_id
    and NULL columns for detailed area breakdowns needed by correlation models.

    The comparison dbt models (sacog_correlations, sacog_weighted_means) need
    access to per-parcel data with geography_id for joining against the reference
    table.  This view provides that by:

      1. Taking all columns from base_canvas_reconciled via bcr.*
      2. Adding geography_id from the parcels staging table
      3. Adding NULL columns for detailed built-form area breakdowns that the
         original base_canvas table schema had but base_canvas_reconciled doesn't
         (these columns exist so that CORR() queries against them return NULL
         gracefully instead of failing on missing columns)

    Materialized as: view (lightweight, always reflects upstream data)
#}
{{ config(materialized='view') }}

SELECT
    bcr.*,
    NULL::double precision AS area_parcel_res_detsf,
    NULL::double precision AS area_parcel_res_detsf_sl,
    NULL::double precision AS area_parcel_res_detsf_ll,
    NULL::double precision AS area_parcel_res_attsf,
    NULL::double precision AS area_parcel_res_mf,
    NULL::double precision AS area_parcel_emp_ret,
    NULL::double precision AS area_parcel_emp_off,
    NULL::double precision AS area_parcel_emp_pub,
    NULL::double precision AS area_parcel_emp_ind,
    NULL::double precision AS area_parcel_emp_military,
    sp.geography_id
FROM {{ ref('base_canvas_reconciled') }} bcr
LEFT JOIN public.sacog_comparison_parcels sp
    ON bcr.parcel_id = sp.parcel_id
