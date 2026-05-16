{#
    Assert that all correlation columns in sacog_summary fall within [-1, 1].

    PostgreSQL's CORR() function should always return values in [-1, 1], but
    floating-point edge cases can produce values outside this range. This singular
    test catches any such anomalies. NULL values (from zero-variance inputs) are
    expected and skipped — the WHERE clause explicitly handles them.

    Returns any row where a non-NULL correlation value lies outside [-1, 1].
#}

SELECT
    'corr_area_gross' AS column_name,
    corr_area_gross AS value
FROM {{ ref('sacog_summary') }}
WHERE corr_area_gross IS NOT NULL AND (corr_area_gross < -1 OR corr_area_gross > 1)

UNION ALL

SELECT 'corr_area_parcel', corr_area_parcel
FROM {{ ref('sacog_summary') }}
WHERE corr_area_parcel IS NOT NULL AND (corr_area_parcel < -1 OR corr_area_parcel > 1)

UNION ALL

SELECT 'corr_area_parcel_res_detsf', corr_area_parcel_res_detsf
FROM {{ ref('sacog_summary') }}
WHERE corr_area_parcel_res_detsf IS NOT NULL AND (corr_area_parcel_res_detsf < -1 OR corr_area_parcel_res_detsf > 1)

UNION ALL

SELECT 'corr_area_parcel_res_detsf_sl', corr_area_parcel_res_detsf_sl
FROM {{ ref('sacog_summary') }}
WHERE corr_area_parcel_res_detsf_sl IS NOT NULL AND (corr_area_parcel_res_detsf_sl < -1 OR corr_area_parcel_res_detsf_sl > 1)

UNION ALL

SELECT 'corr_area_parcel_res_detsf_ll', corr_area_parcel_res_detsf_ll
FROM {{ ref('sacog_summary') }}
WHERE corr_area_parcel_res_detsf_ll IS NOT NULL AND (corr_area_parcel_res_detsf_ll < -1 OR corr_area_parcel_res_detsf_ll > 1)

UNION ALL

SELECT 'corr_area_parcel_res_attsf', corr_area_parcel_res_attsf
FROM {{ ref('sacog_summary') }}
WHERE corr_area_parcel_res_attsf IS NOT NULL AND (corr_area_parcel_res_attsf < -1 OR corr_area_parcel_res_attsf > 1)

UNION ALL

SELECT 'corr_area_parcel_res_mf', corr_area_parcel_res_mf
FROM {{ ref('sacog_summary') }}
WHERE corr_area_parcel_res_mf IS NOT NULL AND (corr_area_parcel_res_mf < -1 OR corr_area_parcel_res_mf > 1)

UNION ALL

SELECT 'corr_area_parcel_res', corr_area_parcel_res
FROM {{ ref('sacog_summary') }}
WHERE corr_area_parcel_res IS NOT NULL AND (corr_area_parcel_res < -1 OR corr_area_parcel_res > 1)

UNION ALL

SELECT 'corr_area_parcel_emp', corr_area_parcel_emp
FROM {{ ref('sacog_summary') }}
WHERE corr_area_parcel_emp IS NOT NULL AND (corr_area_parcel_emp < -1 OR corr_area_parcel_emp > 1)

UNION ALL

SELECT 'corr_area_parcel_emp_ret', corr_area_parcel_emp_ret
FROM {{ ref('sacog_summary') }}
WHERE corr_area_parcel_emp_ret IS NOT NULL AND (corr_area_parcel_emp_ret < -1 OR corr_area_parcel_emp_ret > 1)

UNION ALL

SELECT 'corr_area_parcel_emp_off', corr_area_parcel_emp_off
FROM {{ ref('sacog_summary') }}
WHERE corr_area_parcel_emp_off IS NOT NULL AND (corr_area_parcel_emp_off < -1 OR corr_area_parcel_emp_off > 1)

UNION ALL

SELECT 'corr_area_parcel_emp_pub', corr_area_parcel_emp_pub
FROM {{ ref('sacog_summary') }}
WHERE corr_area_parcel_emp_pub IS NOT NULL AND (corr_area_parcel_emp_pub < -1 OR corr_area_parcel_emp_pub > 1)

UNION ALL

SELECT 'corr_area_parcel_emp_ind', corr_area_parcel_emp_ind
FROM {{ ref('sacog_summary') }}
WHERE corr_area_parcel_emp_ind IS NOT NULL AND (corr_area_parcel_emp_ind < -1 OR corr_area_parcel_emp_ind > 1)

UNION ALL

SELECT 'corr_area_parcel_emp_ag', corr_area_parcel_emp_ag
FROM {{ ref('sacog_summary') }}
WHERE corr_area_parcel_emp_ag IS NOT NULL AND (corr_area_parcel_emp_ag < -1 OR corr_area_parcel_emp_ag > 1)

UNION ALL

SELECT 'corr_area_parcel_emp_military', corr_area_parcel_emp_military
FROM {{ ref('sacog_summary') }}
WHERE corr_area_parcel_emp_military IS NOT NULL AND (corr_area_parcel_emp_military < -1 OR corr_area_parcel_emp_military > 1)

UNION ALL

SELECT 'corr_area_parcel_mixed_use', corr_area_parcel_mixed_use
FROM {{ ref('sacog_summary') }}
WHERE corr_area_parcel_mixed_use IS NOT NULL AND (corr_area_parcel_mixed_use < -1 OR corr_area_parcel_mixed_use > 1)

UNION ALL

SELECT 'corr_area_parcel_no_use', corr_area_parcel_no_use
FROM {{ ref('sacog_summary') }}
WHERE corr_area_parcel_no_use IS NOT NULL AND (corr_area_parcel_no_use < -1 OR corr_area_parcel_no_use > 1)

UNION ALL

SELECT 'corr_intersection_density', corr_intersection_density
FROM {{ ref('sacog_summary') }}
WHERE corr_intersection_density IS NOT NULL AND (corr_intersection_density < -1 OR corr_intersection_density > 1)

UNION ALL

SELECT 'corr_pop', corr_pop
FROM {{ ref('sacog_summary') }}
WHERE corr_pop IS NOT NULL AND (corr_pop < -1 OR corr_pop > 1)

UNION ALL

SELECT 'corr_hh', corr_hh
FROM {{ ref('sacog_summary') }}
WHERE corr_hh IS NOT NULL AND (corr_hh < -1 OR corr_hh > 1)

UNION ALL

SELECT 'corr_du', corr_du
FROM {{ ref('sacog_summary') }}
WHERE corr_du IS NOT NULL AND (corr_du < -1 OR corr_du > 1)

UNION ALL

SELECT 'corr_du_detsf', corr_du_detsf
FROM {{ ref('sacog_summary') }}
WHERE corr_du_detsf IS NOT NULL AND (corr_du_detsf < -1 OR corr_du_detsf > 1)

UNION ALL

SELECT 'corr_du_detsf_sl', corr_du_detsf_sl
FROM {{ ref('sacog_summary') }}
WHERE corr_du_detsf_sl IS NOT NULL AND (corr_du_detsf_sl < -1 OR corr_du_detsf_sl > 1)

UNION ALL

SELECT 'corr_du_detsf_ll', corr_du_detsf_ll
FROM {{ ref('sacog_summary') }}
WHERE corr_du_detsf_ll IS NOT NULL AND (corr_du_detsf_ll < -1 OR corr_du_detsf_ll > 1)

UNION ALL

SELECT 'corr_du_attsf', corr_du_attsf
FROM {{ ref('sacog_summary') }}
WHERE corr_du_attsf IS NOT NULL AND (corr_du_attsf < -1 OR corr_du_attsf > 1)

UNION ALL

SELECT 'corr_du_mf', corr_du_mf
FROM {{ ref('sacog_summary') }}
WHERE corr_du_mf IS NOT NULL AND (corr_du_mf < -1 OR corr_du_mf > 1)

UNION ALL

SELECT 'corr_du_mf2to4', corr_du_mf2to4
FROM {{ ref('sacog_summary') }}
WHERE corr_du_mf2to4 IS NOT NULL AND (corr_du_mf2to4 < -1 OR corr_du_mf2to4 > 1)

UNION ALL

SELECT 'corr_du_mf5p', corr_du_mf5p
FROM {{ ref('sacog_summary') }}
WHERE corr_du_mf5p IS NOT NULL AND (corr_du_mf5p < -1 OR corr_du_mf5p > 1)

UNION ALL

SELECT 'corr_emp', corr_emp
FROM {{ ref('sacog_summary') }}
WHERE corr_emp IS NOT NULL AND (corr_emp < -1 OR corr_emp > 1)

UNION ALL

SELECT 'corr_emp_ret', corr_emp_ret
FROM {{ ref('sacog_summary') }}
WHERE corr_emp_ret IS NOT NULL AND (corr_emp_ret < -1 OR corr_emp_ret > 1)

UNION ALL

SELECT 'corr_emp_retail_services', corr_emp_retail_services
FROM {{ ref('sacog_summary') }}
WHERE corr_emp_retail_services IS NOT NULL AND (corr_emp_retail_services < -1 OR corr_emp_retail_services > 1)

UNION ALL

SELECT 'corr_emp_restaurant', corr_emp_restaurant
FROM {{ ref('sacog_summary') }}
WHERE corr_emp_restaurant IS NOT NULL AND (corr_emp_restaurant < -1 OR corr_emp_restaurant > 1)

UNION ALL

SELECT 'corr_emp_accommodation', corr_emp_accommodation
FROM {{ ref('sacog_summary') }}
WHERE corr_emp_accommodation IS NOT NULL AND (corr_emp_accommodation < -1 OR corr_emp_accommodation > 1)

UNION ALL

SELECT 'corr_emp_arts_entertainment', corr_emp_arts_entertainment
FROM {{ ref('sacog_summary') }}
WHERE corr_emp_arts_entertainment IS NOT NULL AND (corr_emp_arts_entertainment < -1 OR corr_emp_arts_entertainment > 1)

UNION ALL

SELECT 'corr_emp_other_services', corr_emp_other_services
FROM {{ ref('sacog_summary') }}
WHERE corr_emp_other_services IS NOT NULL AND (corr_emp_other_services < -1 OR corr_emp_other_services > 1)

UNION ALL

SELECT 'corr_emp_off', corr_emp_off
FROM {{ ref('sacog_summary') }}
WHERE corr_emp_off IS NOT NULL AND (corr_emp_off < -1 OR corr_emp_off > 1)

UNION ALL

SELECT 'corr_emp_office_services', corr_emp_office_services
FROM {{ ref('sacog_summary') }}
WHERE corr_emp_office_services IS NOT NULL AND (corr_emp_office_services < -1 OR corr_emp_office_services > 1)

UNION ALL

SELECT 'corr_emp_medical_services', corr_emp_medical_services
FROM {{ ref('sacog_summary') }}
WHERE corr_emp_medical_services IS NOT NULL AND (corr_emp_medical_services < -1 OR corr_emp_medical_services > 1)

UNION ALL

SELECT 'corr_emp_pub', corr_emp_pub
FROM {{ ref('sacog_summary') }}
WHERE corr_emp_pub IS NOT NULL AND (corr_emp_pub < -1 OR corr_emp_pub > 1)

UNION ALL

SELECT 'corr_emp_public_admin', corr_emp_public_admin
FROM {{ ref('sacog_summary') }}
WHERE corr_emp_public_admin IS NOT NULL AND (corr_emp_public_admin < -1 OR corr_emp_public_admin > 1)

UNION ALL

SELECT 'corr_emp_education', corr_emp_education
FROM {{ ref('sacog_summary') }}
WHERE corr_emp_education IS NOT NULL AND (corr_emp_education < -1 OR corr_emp_education > 1)

UNION ALL

SELECT 'corr_emp_ind', corr_emp_ind
FROM {{ ref('sacog_summary') }}
WHERE corr_emp_ind IS NOT NULL AND (corr_emp_ind < -1 OR corr_emp_ind > 1)

UNION ALL

SELECT 'corr_emp_manufacturing', corr_emp_manufacturing
FROM {{ ref('sacog_summary') }}
WHERE corr_emp_manufacturing IS NOT NULL AND (corr_emp_manufacturing < -1 OR corr_emp_manufacturing > 1)

UNION ALL

SELECT 'corr_emp_wholesale', corr_emp_wholesale
FROM {{ ref('sacog_summary') }}
WHERE corr_emp_wholesale IS NOT NULL AND (corr_emp_wholesale < -1 OR corr_emp_wholesale > 1)

UNION ALL

SELECT 'corr_emp_transport_warehousing', corr_emp_transport_warehousing
FROM {{ ref('sacog_summary') }}
WHERE corr_emp_transport_warehousing IS NOT NULL AND (corr_emp_transport_warehousing < -1 OR corr_emp_transport_warehousing > 1)

UNION ALL

SELECT 'corr_emp_utilities', corr_emp_utilities
FROM {{ ref('sacog_summary') }}
WHERE corr_emp_utilities IS NOT NULL AND (corr_emp_utilities < -1 OR corr_emp_utilities > 1)

UNION ALL

SELECT 'corr_emp_construction', corr_emp_construction
FROM {{ ref('sacog_summary') }}
WHERE corr_emp_construction IS NOT NULL AND (corr_emp_construction < -1 OR corr_emp_construction > 1)

UNION ALL

SELECT 'corr_emp_ag', corr_emp_ag
FROM {{ ref('sacog_summary') }}
WHERE corr_emp_ag IS NOT NULL AND (corr_emp_ag < -1 OR corr_emp_ag > 1)

UNION ALL

SELECT 'corr_emp_agriculture', corr_emp_agriculture
FROM {{ ref('sacog_summary') }}
WHERE corr_emp_agriculture IS NOT NULL AND (corr_emp_agriculture < -1 OR corr_emp_agriculture > 1)

UNION ALL

SELECT 'corr_emp_extraction', corr_emp_extraction
FROM {{ ref('sacog_summary') }}
WHERE corr_emp_extraction IS NOT NULL AND (corr_emp_extraction < -1 OR corr_emp_extraction > 1)

UNION ALL

SELECT 'corr_emp_military', corr_emp_military
FROM {{ ref('sacog_summary') }}
WHERE corr_emp_military IS NOT NULL AND (corr_emp_military < -1 OR corr_emp_military > 1)

UNION ALL

SELECT 'corr_bldg_area_detsf_sl', corr_bldg_area_detsf_sl
FROM {{ ref('sacog_summary') }}
WHERE corr_bldg_area_detsf_sl IS NOT NULL AND (corr_bldg_area_detsf_sl < -1 OR corr_bldg_area_detsf_sl > 1)

UNION ALL

SELECT 'corr_bldg_area_detsf_ll', corr_bldg_area_detsf_ll
FROM {{ ref('sacog_summary') }}
WHERE corr_bldg_area_detsf_ll IS NOT NULL AND (corr_bldg_area_detsf_ll < -1 OR corr_bldg_area_detsf_ll > 1)

UNION ALL

SELECT 'corr_bldg_area_attsf', corr_bldg_area_attsf
FROM {{ ref('sacog_summary') }}
WHERE corr_bldg_area_attsf IS NOT NULL AND (corr_bldg_area_attsf < -1 OR corr_bldg_area_attsf > 1)

UNION ALL

SELECT 'corr_bldg_area_mf', corr_bldg_area_mf
FROM {{ ref('sacog_summary') }}
WHERE corr_bldg_area_mf IS NOT NULL AND (corr_bldg_area_mf < -1 OR corr_bldg_area_mf > 1)

UNION ALL

SELECT 'corr_bldg_area_retail_services', corr_bldg_area_retail_services
FROM {{ ref('sacog_summary') }}
WHERE corr_bldg_area_retail_services IS NOT NULL AND (corr_bldg_area_retail_services < -1 OR corr_bldg_area_retail_services > 1)

UNION ALL

SELECT 'corr_bldg_area_restaurant', corr_bldg_area_restaurant
FROM {{ ref('sacog_summary') }}
WHERE corr_bldg_area_restaurant IS NOT NULL AND (corr_bldg_area_restaurant < -1 OR corr_bldg_area_restaurant > 1)

UNION ALL

SELECT 'corr_bldg_area_accommodation', corr_bldg_area_accommodation
FROM {{ ref('sacog_summary') }}
WHERE corr_bldg_area_accommodation IS NOT NULL AND (corr_bldg_area_accommodation < -1 OR corr_bldg_area_accommodation > 1)

UNION ALL

SELECT 'corr_bldg_area_arts_entertainment', corr_bldg_area_arts_entertainment
FROM {{ ref('sacog_summary') }}
WHERE corr_bldg_area_arts_entertainment IS NOT NULL AND (corr_bldg_area_arts_entertainment < -1 OR corr_bldg_area_arts_entertainment > 1)

UNION ALL

SELECT 'corr_bldg_area_other_services', corr_bldg_area_other_services
FROM {{ ref('sacog_summary') }}
WHERE corr_bldg_area_other_services IS NOT NULL AND (corr_bldg_area_other_services < -1 OR corr_bldg_area_other_services > 1)

UNION ALL

SELECT 'corr_bldg_area_office_services', corr_bldg_area_office_services
FROM {{ ref('sacog_summary') }}
WHERE corr_bldg_area_office_services IS NOT NULL AND (corr_bldg_area_office_services < -1 OR corr_bldg_area_office_services > 1)

UNION ALL

SELECT 'corr_bldg_area_public_admin', corr_bldg_area_public_admin
FROM {{ ref('sacog_summary') }}
WHERE corr_bldg_area_public_admin IS NOT NULL AND (corr_bldg_area_public_admin < -1 OR corr_bldg_area_public_admin > 1)

UNION ALL

SELECT 'corr_bldg_area_education', corr_bldg_area_education
FROM {{ ref('sacog_summary') }}
WHERE corr_bldg_area_education IS NOT NULL AND (corr_bldg_area_education < -1 OR corr_bldg_area_education > 1)

UNION ALL

SELECT 'corr_bldg_area_medical_services', corr_bldg_area_medical_services
FROM {{ ref('sacog_summary') }}
WHERE corr_bldg_area_medical_services IS NOT NULL AND (corr_bldg_area_medical_services < -1 OR corr_bldg_area_medical_services > 1)

UNION ALL

SELECT 'corr_bldg_area_transport_warehousing', corr_bldg_area_transport_warehousing
FROM {{ ref('sacog_summary') }}
WHERE corr_bldg_area_transport_warehousing IS NOT NULL AND (corr_bldg_area_transport_warehousing < -1 OR corr_bldg_area_transport_warehousing > 1)

UNION ALL

SELECT 'corr_bldg_area_wholesale', corr_bldg_area_wholesale
FROM {{ ref('sacog_summary') }}
WHERE corr_bldg_area_wholesale IS NOT NULL AND (corr_bldg_area_wholesale < -1 OR corr_bldg_area_wholesale > 1)

UNION ALL

SELECT 'corr_residential_irrigated_area', corr_residential_irrigated_area
FROM {{ ref('sacog_summary') }}
WHERE corr_residential_irrigated_area IS NOT NULL AND (corr_residential_irrigated_area < -1 OR corr_residential_irrigated_area > 1)

UNION ALL

SELECT 'corr_commercial_irrigated_area', corr_commercial_irrigated_area
FROM {{ ref('sacog_summary') }}
WHERE corr_commercial_irrigated_area IS NOT NULL AND (corr_commercial_irrigated_area < -1 OR corr_commercial_irrigated_area > 1);
