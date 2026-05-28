{#
    SACOG Correlations — per-column Pearson R correlation between brewgis and reference.

    Computes CORR(bc.col, ref.col) for each paired numeric column between
    the brewgis base_canvas and the v1 reference table, joined on geography_id.

    The column pairs are derived from the ColumnMapping definitions in
    sacog_column_mapping.py. Only columns present in both tables are included.

    Vars:
        comparison_reference_table: Reference table name.

    Materialized as: table (persisted for report generation)
#}
{{ config(materialized='table') }}

{% set ref_table = var('comparison_reference_table', 'sac_cnty_region_base_canvas') %}

{# v3 → v1 column pairs from sacog_column_mapping.get_v1_columns_for_verification()
   These cover area, demographic, employment, and building area mappings #}
{% set column_pairs = [
    ('area_gross', 'acres_gross'),
    ('area_parcel', 'acres_parcel'),
    ('area_parcel_res_detsf', 'acres_parcel_res_detsf'),
    ('area_parcel_res_detsf_sl', 'acres_parcel_res_detsf_sl'),
    ('area_parcel_res_detsf_ll', 'acres_parcel_res_detsf_ll'),
    ('area_parcel_res_attsf', 'acres_parcel_res_attsf'),
    ('area_parcel_res_mf', 'acres_parcel_res_mf'),
    ('area_parcel_res', 'acres_parcel_res'),
    ('area_parcel_emp', 'acres_parcel_emp'),
    ('area_parcel_emp_ret', 'acres_parcel_emp_ret'),
    ('area_parcel_emp_off', 'acres_parcel_emp_off'),
    ('area_parcel_emp_pub', 'acres_parcel_emp_pub'),
    ('area_parcel_emp_ind', 'acres_parcel_emp_ind'),
    ('area_parcel_emp_ag', 'acres_parcel_emp_ag'),
    ('area_parcel_emp_military', 'acres_parcel_emp_military'),
    ('area_parcel_mixed_use', 'acres_parcel_mixed_use'),
    ('area_parcel_no_use', 'acres_parcel_no_use'),
    ('intersection_density', 'intersection_density_sqmi'),
    ('pop', 'pop'),
    ('hh', 'hh'),
    ('du', 'du'),
    ('du_detsf', 'du_detsf'),
    ('du_detsf_sl', 'du_detsf_sl'),
    ('du_detsf_ll', 'du_detsf_ll'),
    ('du_attsf', 'du_attsf'),
    ('du_mf', 'du_mf'),
    ('du_mf2to4', 'du_mf2to4'),
    ('du_mf5p', 'du_mf5p'),
    ('emp', 'emp'),
    ('emp_ret', 'emp_ret'),
    ('emp_retail_services', 'emp_retail_services'),
    ('emp_restaurant', 'emp_restaurant'),
    ('emp_accommodation', 'emp_accommodation'),
    ('emp_arts_entertainment', 'emp_arts_entertainment'),
    ('emp_other_services', 'emp_other_services'),
    ('emp_off', 'emp_off'),
    ('emp_office_services', 'emp_office_services'),
    ('emp_medical_services', 'emp_medical_services'),
    ('emp_pub', 'emp_pub'),
    ('emp_public_admin', 'emp_public_admin'),
    ('emp_education', 'emp_education'),
    ('emp_ind', 'emp_ind'),
    ('emp_manufacturing', 'emp_manufacturing'),
    ('emp_wholesale', 'emp_wholesale'),
    ('emp_transport_warehousing', 'emp_transport_warehousing'),
    ('emp_utilities', 'emp_utilities'),
    ('emp_construction', 'emp_construction'),
    ('emp_ag', 'emp_ag'),
    ('emp_agriculture', 'emp_agriculture'),
    ('emp_extraction', 'emp_extraction'),
    ('emp_military', 'emp_military'),
    ('bldg_area_detsf_sl', 'bldg_sqft_detsf_sl'),
    ('bldg_area_detsf_ll', 'bldg_sqft_detsf_ll'),
    ('bldg_area_attsf', 'bldg_sqft_attsf'),
    ('bldg_area_mf', 'bldg_sqft_mf'),
    ('bldg_area_retail_services', 'bldg_sqft_retail_services'),
    ('bldg_area_restaurant', 'bldg_sqft_restaurant'),
    ('bldg_area_accommodation', 'bldg_sqft_accommodation'),
    ('bldg_area_arts_entertainment', 'bldg_sqft_arts_entertainment'),
    ('bldg_area_other_services', 'bldg_sqft_other_services'),
    ('bldg_area_office_services', 'bldg_sqft_office_services'),
    ('bldg_area_public_admin', 'bldg_sqft_public_admin'),
    ('bldg_area_education', 'bldg_sqft_education'),
    ('bldg_area_medical_services', 'bldg_sqft_medical_services'),
    ('bldg_area_transport_warehousing', 'bldg_sqft_transport_warehousing'),
    ('bldg_area_wholesale', 'bldg_sqft_wholesale'),
    ('residential_irrigated_area', 'residential_irrigated_sqft'),
    ('commercial_irrigated_area', 'commercial_irrigated_sqft'),
] %}

SELECT
{% for v3_col, v1_col in column_pairs %}
    CORR(bc."{{ v3_col }}", ref."{{ v1_col }}") AS "{{ v3_col }}"{% if not loop.last %},{% endif %}
{% endfor %}
FROM {{ ref('sacog_brewgis_comparison_view') }} bc
INNER JOIN {{ ref_table }} ref ON bc.geography_id = ref.geography_id
WHERE bc.geography_id IS NOT NULL
