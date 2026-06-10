MODEL (
  name brewgis.comparison.sacog_correlations,
  kind FULL
);

-- SACOG Correlations — per-column area-weighted Pearson R between brewgis and reference.
--
-- Uses area_gross as the weighting factor so that larger parcels contribute
-- proportionally more to the correlation, preventing near-zero parcels from
-- dominating the metric.

WITH base AS (
    SELECT
        COALESCE(NULLIF(area_gross, 0), NULLIF(acres_gross * 4046.86, 0), 1.0) AS w,
        bc.*,
        acres_gross,
        acres_parcel,
        acres_parcel_emp,
        acres_parcel_emp_ag,
        acres_parcel_emp_ind,
        acres_parcel_emp_military,
        acres_parcel_emp_off,
        acres_parcel_emp_pub,
        acres_parcel_emp_ret,
        acres_parcel_mixed_use,
        acres_parcel_no_use,
        acres_parcel_res,
        acres_parcel_res_attsf,
        acres_parcel_res_detsf,
        acres_parcel_res_detsf_ll,
        acres_parcel_res_detsf_sl,
        acres_parcel_res_mf,
        bldg_sqft_accommodation,
        bldg_sqft_arts_entertainment,
        bldg_sqft_attsf,
        bldg_sqft_detsf_ll,
        bldg_sqft_detsf_sl,
        bldg_sqft_education,
        bldg_sqft_medical_services,
        bldg_sqft_mf,
        bldg_sqft_office_services,
        bldg_sqft_other_services,
        bldg_sqft_public_admin,
        bldg_sqft_restaurant,
        bldg_sqft_retail_services,
        bldg_sqft_transport_warehousing,
        bldg_sqft_wholesale,
        commercial_irrigated_sqft,
        ref.du AS ref_du,
        ref.du_attsf AS ref_du_attsf,
        ref.du_detsf AS ref_du_detsf,
        ref.du_detsf_ll AS ref_du_detsf_ll,
        ref.du_detsf_sl AS ref_du_detsf_sl,
        ref.du_mf AS ref_du_mf,
        ref.du_mf2to4 AS ref_du_mf2to4,
        ref.du_mf5p AS ref_du_mf5p,
        ref.emp AS ref_emp,
        ref.emp_accommodation AS ref_emp_accommodation,
        ref.emp_ag AS ref_emp_ag,
        ref.emp_agriculture AS ref_emp_agriculture,
        ref.emp_arts_entertainment AS ref_emp_arts_entertainment,
        ref.emp_construction AS ref_emp_construction,
        ref.emp_education AS ref_emp_education,
        ref.emp_extraction AS ref_emp_extraction,
        ref.emp_ind AS ref_emp_ind,
        ref.emp_manufacturing AS ref_emp_manufacturing,
        ref.emp_medical_services AS ref_emp_medical_services,
        ref.emp_military AS ref_emp_military,
        ref.emp_off AS ref_emp_off,
        ref.emp_office_services AS ref_emp_office_services,
        ref.emp_other_services AS ref_emp_other_services,
        ref.emp_pub AS ref_emp_pub,
        ref.emp_public_admin AS ref_emp_public_admin,
        ref.emp_restaurant AS ref_emp_restaurant,
        ref.emp_ret AS ref_emp_ret,
        ref.emp_retail_services AS ref_emp_retail_services,
        ref.emp_transport_warehousing AS ref_emp_transport_warehousing,
        ref.emp_utilities AS ref_emp_utilities,
        ref.emp_wholesale AS ref_emp_wholesale,
        ref.hh AS ref_hh,
        intersection_density_sqmi,
        ref.pop AS ref_pop,
        residential_irrigated_sqft
    FROM brewgis.comparison.sacog_brewgis_comparison_view bc
    INNER JOIN public.sac_cnty_region_base_canvas ref ON bc.geography_id = ref.geography_id
    WHERE bc.geography_id IS NOT NULL
),

stats AS (
    SELECT
        SUM(w) AS sw,
        -- area_gross
        SUM(w * area_gross) AS swx_area_gross,
        SUM(w * acres_gross) AS swy_area_gross,
        SUM(w * area_gross * area_gross) AS swxx_area_gross,
        SUM(w * acres_gross * acres_gross) AS swyy_area_gross,
        SUM(w * area_gross * acres_gross) AS swxy_area_gross,
        -- area_parcel
        SUM(w * area_parcel) AS swx_area_parcel,
        SUM(w * acres_parcel) AS swy_area_parcel,
        SUM(w * area_parcel * area_parcel) AS swxx_area_parcel,
        SUM(w * acres_parcel * acres_parcel) AS swyy_area_parcel,
        SUM(w * area_parcel * acres_parcel) AS swxy_area_parcel,
        -- area_parcel_res_detsf
        SUM(w * area_parcel_res_detsf) AS swx_area_parcel_res_detsf,
        SUM(w * acres_parcel_res_detsf) AS swy_area_parcel_res_detsf,
        SUM(w * area_parcel_res_detsf * area_parcel_res_detsf) AS swxx_area_parcel_res_detsf,
        SUM(w * acres_parcel_res_detsf * acres_parcel_res_detsf) AS swyy_area_parcel_res_detsf,
        SUM(w * area_parcel_res_detsf * acres_parcel_res_detsf) AS swxy_area_parcel_res_detsf,
        -- area_parcel_res_detsf_sl
        SUM(w * area_parcel_res_detsf_sl) AS swx_area_parcel_res_detsf_sl,
        SUM(w * acres_parcel_res_detsf_sl) AS swy_area_parcel_res_detsf_sl,
        SUM(w * area_parcel_res_detsf_sl * area_parcel_res_detsf_sl) AS swxx_area_parcel_res_detsf_sl,
        SUM(w * acres_parcel_res_detsf_sl * acres_parcel_res_detsf_sl) AS swyy_area_parcel_res_detsf_sl,
        SUM(w * area_parcel_res_detsf_sl * acres_parcel_res_detsf_sl) AS swxy_area_parcel_res_detsf_sl,
        -- area_parcel_res_detsf_ll
        SUM(w * area_parcel_res_detsf_ll) AS swx_area_parcel_res_detsf_ll,
        SUM(w * acres_parcel_res_detsf_ll) AS swy_area_parcel_res_detsf_ll,
        SUM(w * area_parcel_res_detsf_ll * area_parcel_res_detsf_ll) AS swxx_area_parcel_res_detsf_ll,
        SUM(w * acres_parcel_res_detsf_ll * acres_parcel_res_detsf_ll) AS swyy_area_parcel_res_detsf_ll,
        SUM(w * area_parcel_res_detsf_ll * acres_parcel_res_detsf_ll) AS swxy_area_parcel_res_detsf_ll,
        -- area_parcel_res_attsf
        SUM(w * area_parcel_res_attsf) AS swx_area_parcel_res_attsf,
        SUM(w * acres_parcel_res_attsf) AS swy_area_parcel_res_attsf,
        SUM(w * area_parcel_res_attsf * area_parcel_res_attsf) AS swxx_area_parcel_res_attsf,
        SUM(w * acres_parcel_res_attsf * acres_parcel_res_attsf) AS swyy_area_parcel_res_attsf,
        SUM(w * area_parcel_res_attsf * acres_parcel_res_attsf) AS swxy_area_parcel_res_attsf,
        -- area_parcel_res_mf
        SUM(w * area_parcel_res_mf) AS swx_area_parcel_res_mf,
        SUM(w * acres_parcel_res_mf) AS swy_area_parcel_res_mf,
        SUM(w * area_parcel_res_mf * area_parcel_res_mf) AS swxx_area_parcel_res_mf,
        SUM(w * acres_parcel_res_mf * acres_parcel_res_mf) AS swyy_area_parcel_res_mf,
        SUM(w * area_parcel_res_mf * acres_parcel_res_mf) AS swxy_area_parcel_res_mf,
        -- area_parcel_res
        SUM(w * area_parcel_res) AS swx_area_parcel_res,
        SUM(w * acres_parcel_res) AS swy_area_parcel_res,
        SUM(w * area_parcel_res * area_parcel_res) AS swxx_area_parcel_res,
        SUM(w * acres_parcel_res * acres_parcel_res) AS swyy_area_parcel_res,
        SUM(w * area_parcel_res * acres_parcel_res) AS swxy_area_parcel_res,
        -- area_parcel_emp
        SUM(w * area_parcel_emp) AS swx_area_parcel_emp,
        SUM(w * acres_parcel_emp) AS swy_area_parcel_emp,
        SUM(w * area_parcel_emp * area_parcel_emp) AS swxx_area_parcel_emp,
        SUM(w * acres_parcel_emp * acres_parcel_emp) AS swyy_area_parcel_emp,
        SUM(w * area_parcel_emp * acres_parcel_emp) AS swxy_area_parcel_emp,
        -- area_parcel_emp_ret
        SUM(w * area_parcel_emp_ret) AS swx_area_parcel_emp_ret,
        SUM(w * acres_parcel_emp_ret) AS swy_area_parcel_emp_ret,
        SUM(w * area_parcel_emp_ret * area_parcel_emp_ret) AS swxx_area_parcel_emp_ret,
        SUM(w * acres_parcel_emp_ret * acres_parcel_emp_ret) AS swyy_area_parcel_emp_ret,
        SUM(w * area_parcel_emp_ret * acres_parcel_emp_ret) AS swxy_area_parcel_emp_ret,
        -- area_parcel_emp_off
        SUM(w * area_parcel_emp_off) AS swx_area_parcel_emp_off,
        SUM(w * acres_parcel_emp_off) AS swy_area_parcel_emp_off,
        SUM(w * area_parcel_emp_off * area_parcel_emp_off) AS swxx_area_parcel_emp_off,
        SUM(w * acres_parcel_emp_off * acres_parcel_emp_off) AS swyy_area_parcel_emp_off,
        SUM(w * area_parcel_emp_off * acres_parcel_emp_off) AS swxy_area_parcel_emp_off,
        -- area_parcel_emp_pub
        SUM(w * area_parcel_emp_pub) AS swx_area_parcel_emp_pub,
        SUM(w * acres_parcel_emp_pub) AS swy_area_parcel_emp_pub,
        SUM(w * area_parcel_emp_pub * area_parcel_emp_pub) AS swxx_area_parcel_emp_pub,
        SUM(w * acres_parcel_emp_pub * acres_parcel_emp_pub) AS swyy_area_parcel_emp_pub,
        SUM(w * area_parcel_emp_pub * acres_parcel_emp_pub) AS swxy_area_parcel_emp_pub,
        -- area_parcel_emp_ind
        SUM(w * area_parcel_emp_ind) AS swx_area_parcel_emp_ind,
        SUM(w * acres_parcel_emp_ind) AS swy_area_parcel_emp_ind,
        SUM(w * area_parcel_emp_ind * area_parcel_emp_ind) AS swxx_area_parcel_emp_ind,
        SUM(w * acres_parcel_emp_ind * acres_parcel_emp_ind) AS swyy_area_parcel_emp_ind,
        SUM(w * area_parcel_emp_ind * acres_parcel_emp_ind) AS swxy_area_parcel_emp_ind,
        -- area_parcel_emp_ag
        SUM(w * area_parcel_emp_ag) AS swx_area_parcel_emp_ag,
        SUM(w * acres_parcel_emp_ag) AS swy_area_parcel_emp_ag,
        SUM(w * area_parcel_emp_ag * area_parcel_emp_ag) AS swxx_area_parcel_emp_ag,
        SUM(w * acres_parcel_emp_ag * acres_parcel_emp_ag) AS swyy_area_parcel_emp_ag,
        SUM(w * area_parcel_emp_ag * acres_parcel_emp_ag) AS swxy_area_parcel_emp_ag,
        -- area_parcel_emp_military
        SUM(w * area_parcel_emp_military) AS swx_area_parcel_emp_military,
        SUM(w * acres_parcel_emp_military) AS swy_area_parcel_emp_military,
        SUM(w * area_parcel_emp_military * area_parcel_emp_military) AS swxx_area_parcel_emp_military,
        SUM(w * acres_parcel_emp_military * acres_parcel_emp_military) AS swyy_area_parcel_emp_military,
        SUM(w * area_parcel_emp_military * acres_parcel_emp_military) AS swxy_area_parcel_emp_military,
        -- area_parcel_mixed_use
        SUM(w * area_parcel_mixed_use) AS swx_area_parcel_mixed_use,
        SUM(w * acres_parcel_mixed_use) AS swy_area_parcel_mixed_use,
        SUM(w * area_parcel_mixed_use * area_parcel_mixed_use) AS swxx_area_parcel_mixed_use,
        SUM(w * acres_parcel_mixed_use * acres_parcel_mixed_use) AS swyy_area_parcel_mixed_use,
        SUM(w * area_parcel_mixed_use * acres_parcel_mixed_use) AS swxy_area_parcel_mixed_use,
        -- area_parcel_no_use
        SUM(w * area_parcel_no_use) AS swx_area_parcel_no_use,
        SUM(w * acres_parcel_no_use) AS swy_area_parcel_no_use,
        SUM(w * area_parcel_no_use * area_parcel_no_use) AS swxx_area_parcel_no_use,
        SUM(w * acres_parcel_no_use * acres_parcel_no_use) AS swyy_area_parcel_no_use,
        SUM(w * area_parcel_no_use * acres_parcel_no_use) AS swxy_area_parcel_no_use,
        -- intersection_density
        SUM(w * intersection_density) AS swx_intersection_density,
        SUM(w * intersection_density_sqmi) AS swy_intersection_density,
        SUM(w * intersection_density * intersection_density) AS swxx_intersection_density,
        SUM(w * intersection_density_sqmi * intersection_density_sqmi) AS swyy_intersection_density,
        SUM(w * intersection_density * intersection_density_sqmi) AS swxy_intersection_density,
        -- pop
        SUM(w * pop) AS swx_pop,
        SUM(w * ref_pop) AS swy_pop,
        SUM(w * pop * pop) AS swxx_pop,
        SUM(w * pop * pop) AS swyy_pop,
        SUM(w * pop * pop) AS swxy_pop,
        -- hh
        SUM(w * hh) AS swx_hh,
        SUM(w * ref_hh) AS swy_hh,
        SUM(w * hh * hh) AS swxx_hh,
        SUM(w * hh * hh) AS swyy_hh,
        SUM(w * hh * hh) AS swxy_hh,
        -- du
        SUM(w * du) AS swx_du,
        SUM(w * ref_du) AS swy_du,
        SUM(w * du * du) AS swxx_du,
        SUM(w * du * du) AS swyy_du,
        SUM(w * du * du) AS swxy_du,
        -- du_detsf
        SUM(w * du_detsf) AS swx_du_detsf,
        SUM(w * ref_du_detsf) AS swy_du_detsf,
        SUM(w * du_detsf * du_detsf) AS swxx_du_detsf,
        SUM(w * du_detsf * du_detsf) AS swyy_du_detsf,
        SUM(w * du_detsf * du_detsf) AS swxy_du_detsf,
        -- du_detsf_sl
        SUM(w * du_detsf_sl) AS swx_du_detsf_sl,
        SUM(w * ref_du_detsf_sl) AS swy_du_detsf_sl,
        SUM(w * du_detsf_sl * du_detsf_sl) AS swxx_du_detsf_sl,
        SUM(w * du_detsf_sl * du_detsf_sl) AS swyy_du_detsf_sl,
        SUM(w * du_detsf_sl * du_detsf_sl) AS swxy_du_detsf_sl,
        -- du_detsf_ll
        SUM(w * du_detsf_ll) AS swx_du_detsf_ll,
        SUM(w * ref_du_detsf_ll) AS swy_du_detsf_ll,
        SUM(w * du_detsf_ll * du_detsf_ll) AS swxx_du_detsf_ll,
        SUM(w * du_detsf_ll * du_detsf_ll) AS swyy_du_detsf_ll,
        SUM(w * du_detsf_ll * du_detsf_ll) AS swxy_du_detsf_ll,
        -- du_attsf
        SUM(w * du_attsf) AS swx_du_attsf,
        SUM(w * ref_du_attsf) AS swy_du_attsf,
        SUM(w * du_attsf * du_attsf) AS swxx_du_attsf,
        SUM(w * du_attsf * du_attsf) AS swyy_du_attsf,
        SUM(w * du_attsf * du_attsf) AS swxy_du_attsf,
        -- du_mf
        SUM(w * du_mf) AS swx_du_mf,
        SUM(w * ref_du_mf) AS swy_du_mf,
        SUM(w * du_mf * du_mf) AS swxx_du_mf,
        SUM(w * du_mf * du_mf) AS swyy_du_mf,
        SUM(w * du_mf * du_mf) AS swxy_du_mf,
        -- du_mf2to4
        SUM(w * du_mf2to4) AS swx_du_mf2to4,
        SUM(w * ref_du_mf2to4) AS swy_du_mf2to4,
        SUM(w * du_mf2to4 * du_mf2to4) AS swxx_du_mf2to4,
        SUM(w * du_mf2to4 * du_mf2to4) AS swyy_du_mf2to4,
        SUM(w * du_mf2to4 * du_mf2to4) AS swxy_du_mf2to4,
        -- du_mf5p
        SUM(w * du_mf5p) AS swx_du_mf5p,
        SUM(w * ref_du_mf5p) AS swy_du_mf5p,
        SUM(w * du_mf5p * du_mf5p) AS swxx_du_mf5p,
        SUM(w * du_mf5p * du_mf5p) AS swyy_du_mf5p,
        SUM(w * du_mf5p * du_mf5p) AS swxy_du_mf5p,
        -- emp
        SUM(w * emp) AS swx_emp,
        SUM(w * ref_emp) AS swy_emp,
        SUM(w * emp * emp) AS swxx_emp,
        SUM(w * emp * emp) AS swyy_emp,
        SUM(w * emp * emp) AS swxy_emp,
        -- emp_ret
        SUM(w * emp_ret) AS swx_emp_ret,
        SUM(w * ref_emp_ret) AS swy_emp_ret,
        SUM(w * emp_ret * emp_ret) AS swxx_emp_ret,
        SUM(w * emp_ret * emp_ret) AS swyy_emp_ret,
        SUM(w * emp_ret * emp_ret) AS swxy_emp_ret,
        -- emp_retail_services
        SUM(w * emp_retail_services) AS swx_emp_retail_services,
        SUM(w * ref_emp_retail_services) AS swy_emp_retail_services,
        SUM(w * emp_retail_services * emp_retail_services) AS swxx_emp_retail_services,
        SUM(w * emp_retail_services * emp_retail_services) AS swyy_emp_retail_services,
        SUM(w * emp_retail_services * emp_retail_services) AS swxy_emp_retail_services,
        -- emp_restaurant
        SUM(w * emp_restaurant) AS swx_emp_restaurant,
        SUM(w * ref_emp_restaurant) AS swy_emp_restaurant,
        SUM(w * emp_restaurant * emp_restaurant) AS swxx_emp_restaurant,
        SUM(w * emp_restaurant * emp_restaurant) AS swyy_emp_restaurant,
        SUM(w * emp_restaurant * emp_restaurant) AS swxy_emp_restaurant,
        -- emp_accommodation
        SUM(w * emp_accommodation) AS swx_emp_accommodation,
        SUM(w * ref_emp_accommodation) AS swy_emp_accommodation,
        SUM(w * emp_accommodation * emp_accommodation) AS swxx_emp_accommodation,
        SUM(w * emp_accommodation * emp_accommodation) AS swyy_emp_accommodation,
        SUM(w * emp_accommodation * emp_accommodation) AS swxy_emp_accommodation,
        -- emp_arts_entertainment
        SUM(w * emp_arts_entertainment) AS swx_emp_arts_entertainment,
        SUM(w * ref_emp_arts_entertainment) AS swy_emp_arts_entertainment,
        SUM(w * emp_arts_entertainment * emp_arts_entertainment) AS swxx_emp_arts_entertainment,
        SUM(w * emp_arts_entertainment * emp_arts_entertainment) AS swyy_emp_arts_entertainment,
        SUM(w * emp_arts_entertainment * emp_arts_entertainment) AS swxy_emp_arts_entertainment,
        -- emp_other_services
        SUM(w * emp_other_services) AS swx_emp_other_services,
        SUM(w * ref_emp_other_services) AS swy_emp_other_services,
        SUM(w * emp_other_services * emp_other_services) AS swxx_emp_other_services,
        SUM(w * emp_other_services * emp_other_services) AS swyy_emp_other_services,
        SUM(w * emp_other_services * emp_other_services) AS swxy_emp_other_services,
        -- emp_off
        SUM(w * emp_off) AS swx_emp_off,
        SUM(w * ref_emp_off) AS swy_emp_off,
        SUM(w * emp_off * emp_off) AS swxx_emp_off,
        SUM(w * emp_off * emp_off) AS swyy_emp_off,
        SUM(w * emp_off * emp_off) AS swxy_emp_off,
        -- emp_office_services
        SUM(w * emp_office_services) AS swx_emp_office_services,
        SUM(w * ref_emp_office_services) AS swy_emp_office_services,
        SUM(w * emp_office_services * emp_office_services) AS swxx_emp_office_services,
        SUM(w * emp_office_services * emp_office_services) AS swyy_emp_office_services,
        SUM(w * emp_office_services * emp_office_services) AS swxy_emp_office_services,
        -- emp_medical_services
        SUM(w * emp_medical_services) AS swx_emp_medical_services,
        SUM(w * ref_emp_medical_services) AS swy_emp_medical_services,
        SUM(w * emp_medical_services * emp_medical_services) AS swxx_emp_medical_services,
        SUM(w * emp_medical_services * emp_medical_services) AS swyy_emp_medical_services,
        SUM(w * emp_medical_services * emp_medical_services) AS swxy_emp_medical_services,
        -- emp_pub
        SUM(w * emp_pub) AS swx_emp_pub,
        SUM(w * ref_emp_pub) AS swy_emp_pub,
        SUM(w * emp_pub * emp_pub) AS swxx_emp_pub,
        SUM(w * emp_pub * emp_pub) AS swyy_emp_pub,
        SUM(w * emp_pub * emp_pub) AS swxy_emp_pub,
        -- emp_public_admin
        SUM(w * emp_public_admin) AS swx_emp_public_admin,
        SUM(w * ref_emp_public_admin) AS swy_emp_public_admin,
        SUM(w * emp_public_admin * emp_public_admin) AS swxx_emp_public_admin,
        SUM(w * emp_public_admin * emp_public_admin) AS swyy_emp_public_admin,
        SUM(w * emp_public_admin * emp_public_admin) AS swxy_emp_public_admin,
        -- emp_education
        SUM(w * emp_education) AS swx_emp_education,
        SUM(w * ref_emp_education) AS swy_emp_education,
        SUM(w * emp_education * emp_education) AS swxx_emp_education,
        SUM(w * emp_education * emp_education) AS swyy_emp_education,
        SUM(w * emp_education * emp_education) AS swxy_emp_education,
        -- emp_ind
        SUM(w * emp_ind) AS swx_emp_ind,
        SUM(w * ref_emp_ind) AS swy_emp_ind,
        SUM(w * emp_ind * emp_ind) AS swxx_emp_ind,
        SUM(w * emp_ind * emp_ind) AS swyy_emp_ind,
        SUM(w * emp_ind * emp_ind) AS swxy_emp_ind,
        -- emp_manufacturing
        SUM(w * emp_manufacturing) AS swx_emp_manufacturing,
        SUM(w * ref_emp_manufacturing) AS swy_emp_manufacturing,
        SUM(w * emp_manufacturing * emp_manufacturing) AS swxx_emp_manufacturing,
        SUM(w * emp_manufacturing * emp_manufacturing) AS swyy_emp_manufacturing,
        SUM(w * emp_manufacturing * emp_manufacturing) AS swxy_emp_manufacturing,
        -- emp_wholesale
        SUM(w * emp_wholesale) AS swx_emp_wholesale,
        SUM(w * ref_emp_wholesale) AS swy_emp_wholesale,
        SUM(w * emp_wholesale * emp_wholesale) AS swxx_emp_wholesale,
        SUM(w * emp_wholesale * emp_wholesale) AS swyy_emp_wholesale,
        SUM(w * emp_wholesale * emp_wholesale) AS swxy_emp_wholesale,
        -- emp_transport_warehousing
        SUM(w * emp_transport_warehousing) AS swx_emp_transport_warehousing,
        SUM(w * ref_emp_transport_warehousing) AS swy_emp_transport_warehousing,
        SUM(w * emp_transport_warehousing * emp_transport_warehousing) AS swxx_emp_transport_warehousing,
        SUM(w * emp_transport_warehousing * emp_transport_warehousing) AS swyy_emp_transport_warehousing,
        SUM(w * emp_transport_warehousing * emp_transport_warehousing) AS swxy_emp_transport_warehousing,
        -- emp_utilities
        SUM(w * emp_utilities) AS swx_emp_utilities,
        SUM(w * ref_emp_utilities) AS swy_emp_utilities,
        SUM(w * emp_utilities * emp_utilities) AS swxx_emp_utilities,
        SUM(w * emp_utilities * emp_utilities) AS swyy_emp_utilities,
        SUM(w * emp_utilities * emp_utilities) AS swxy_emp_utilities,
        -- emp_construction
        SUM(w * emp_construction) AS swx_emp_construction,
        SUM(w * ref_emp_construction) AS swy_emp_construction,
        SUM(w * emp_construction * emp_construction) AS swxx_emp_construction,
        SUM(w * emp_construction * emp_construction) AS swyy_emp_construction,
        SUM(w * emp_construction * emp_construction) AS swxy_emp_construction,
        -- emp_ag
        SUM(w * emp_ag) AS swx_emp_ag,
        SUM(w * ref_emp_ag) AS swy_emp_ag,
        SUM(w * emp_ag * emp_ag) AS swxx_emp_ag,
        SUM(w * emp_ag * emp_ag) AS swyy_emp_ag,
        SUM(w * emp_ag * emp_ag) AS swxy_emp_ag,
        -- emp_agriculture
        SUM(w * emp_agriculture) AS swx_emp_agriculture,
        SUM(w * ref_emp_agriculture) AS swy_emp_agriculture,
        SUM(w * emp_agriculture * emp_agriculture) AS swxx_emp_agriculture,
        SUM(w * emp_agriculture * emp_agriculture) AS swyy_emp_agriculture,
        SUM(w * emp_agriculture * emp_agriculture) AS swxy_emp_agriculture,
        -- emp_extraction
        SUM(w * emp_extraction) AS swx_emp_extraction,
        SUM(w * ref_emp_extraction) AS swy_emp_extraction,
        SUM(w * emp_extraction * emp_extraction) AS swxx_emp_extraction,
        SUM(w * emp_extraction * emp_extraction) AS swyy_emp_extraction,
        SUM(w * emp_extraction * emp_extraction) AS swxy_emp_extraction,
        -- emp_military
        SUM(w * emp_military) AS swx_emp_military,
        SUM(w * ref_emp_military) AS swy_emp_military,
        SUM(w * emp_military * emp_military) AS swxx_emp_military,
        SUM(w * emp_military * emp_military) AS swyy_emp_military,
        SUM(w * emp_military * emp_military) AS swxy_emp_military,
        -- bldg_area_detsf_sl
        SUM(w * bldg_area_detsf_sl) AS swx_bldg_area_detsf_sl,
        SUM(w * bldg_sqft_detsf_sl) AS swy_bldg_area_detsf_sl,
        SUM(w * bldg_area_detsf_sl * bldg_area_detsf_sl) AS swxx_bldg_area_detsf_sl,
        SUM(w * bldg_sqft_detsf_sl * bldg_sqft_detsf_sl) AS swyy_bldg_area_detsf_sl,
        SUM(w * bldg_area_detsf_sl * bldg_sqft_detsf_sl) AS swxy_bldg_area_detsf_sl,
        -- bldg_area_detsf_ll
        SUM(w * bldg_area_detsf_ll) AS swx_bldg_area_detsf_ll,
        SUM(w * bldg_sqft_detsf_ll) AS swy_bldg_area_detsf_ll,
        SUM(w * bldg_area_detsf_ll * bldg_area_detsf_ll) AS swxx_bldg_area_detsf_ll,
        SUM(w * bldg_sqft_detsf_ll * bldg_sqft_detsf_ll) AS swyy_bldg_area_detsf_ll,
        SUM(w * bldg_area_detsf_ll * bldg_sqft_detsf_ll) AS swxy_bldg_area_detsf_ll,
        -- bldg_area_attsf
        SUM(w * bldg_area_attsf) AS swx_bldg_area_attsf,
        SUM(w * bldg_sqft_attsf) AS swy_bldg_area_attsf,
        SUM(w * bldg_area_attsf * bldg_area_attsf) AS swxx_bldg_area_attsf,
        SUM(w * bldg_sqft_attsf * bldg_sqft_attsf) AS swyy_bldg_area_attsf,
        SUM(w * bldg_area_attsf * bldg_sqft_attsf) AS swxy_bldg_area_attsf,
        -- bldg_area_mf
        SUM(w * bldg_area_mf) AS swx_bldg_area_mf,
        SUM(w * bldg_sqft_mf) AS swy_bldg_area_mf,
        SUM(w * bldg_area_mf * bldg_area_mf) AS swxx_bldg_area_mf,
        SUM(w * bldg_sqft_mf * bldg_sqft_mf) AS swyy_bldg_area_mf,
        SUM(w * bldg_area_mf * bldg_sqft_mf) AS swxy_bldg_area_mf,
        -- bldg_area_retail_services
        SUM(w * bldg_area_retail_services) AS swx_bldg_area_retail_services,
        SUM(w * bldg_sqft_retail_services) AS swy_bldg_area_retail_services,
        SUM(w * bldg_area_retail_services * bldg_area_retail_services) AS swxx_bldg_area_retail_services,
        SUM(w * bldg_sqft_retail_services * bldg_sqft_retail_services) AS swyy_bldg_area_retail_services,
        SUM(w * bldg_area_retail_services * bldg_sqft_retail_services) AS swxy_bldg_area_retail_services,
        -- bldg_area_restaurant
        SUM(w * bldg_area_restaurant) AS swx_bldg_area_restaurant,
        SUM(w * bldg_sqft_restaurant) AS swy_bldg_area_restaurant,
        SUM(w * bldg_area_restaurant * bldg_area_restaurant) AS swxx_bldg_area_restaurant,
        SUM(w * bldg_sqft_restaurant * bldg_sqft_restaurant) AS swyy_bldg_area_restaurant,
        SUM(w * bldg_area_restaurant * bldg_sqft_restaurant) AS swxy_bldg_area_restaurant,
        -- bldg_area_accommodation
        SUM(w * bldg_area_accommodation) AS swx_bldg_area_accommodation,
        SUM(w * bldg_sqft_accommodation) AS swy_bldg_area_accommodation,
        SUM(w * bldg_area_accommodation * bldg_area_accommodation) AS swxx_bldg_area_accommodation,
        SUM(w * bldg_sqft_accommodation * bldg_sqft_accommodation) AS swyy_bldg_area_accommodation,
        SUM(w * bldg_area_accommodation * bldg_sqft_accommodation) AS swxy_bldg_area_accommodation,
        -- bldg_area_arts_entertainment
        SUM(w * bldg_area_arts_entertainment) AS swx_bldg_area_arts_entertainment,
        SUM(w * bldg_sqft_arts_entertainment) AS swy_bldg_area_arts_entertainment,
        SUM(w * bldg_area_arts_entertainment * bldg_area_arts_entertainment) AS swxx_bldg_area_arts_entertainment,
        SUM(w * bldg_sqft_arts_entertainment * bldg_sqft_arts_entertainment) AS swyy_bldg_area_arts_entertainment,
        SUM(w * bldg_area_arts_entertainment * bldg_sqft_arts_entertainment) AS swxy_bldg_area_arts_entertainment,
        -- bldg_area_other_services
        SUM(w * bldg_area_other_services) AS swx_bldg_area_other_services,
        SUM(w * bldg_sqft_other_services) AS swy_bldg_area_other_services,
        SUM(w * bldg_area_other_services * bldg_area_other_services) AS swxx_bldg_area_other_services,
        SUM(w * bldg_sqft_other_services * bldg_sqft_other_services) AS swyy_bldg_area_other_services,
        SUM(w * bldg_area_other_services * bldg_sqft_other_services) AS swxy_bldg_area_other_services,
        -- bldg_area_office_services
        SUM(w * bldg_area_office_services) AS swx_bldg_area_office_services,
        SUM(w * bldg_sqft_office_services) AS swy_bldg_area_office_services,
        SUM(w * bldg_area_office_services * bldg_area_office_services) AS swxx_bldg_area_office_services,
        SUM(w * bldg_sqft_office_services * bldg_sqft_office_services) AS swyy_bldg_area_office_services,
        SUM(w * bldg_area_office_services * bldg_sqft_office_services) AS swxy_bldg_area_office_services,
        -- bldg_area_public_admin
        SUM(w * bldg_area_public_admin) AS swx_bldg_area_public_admin,
        SUM(w * bldg_sqft_public_admin) AS swy_bldg_area_public_admin,
        SUM(w * bldg_area_public_admin * bldg_area_public_admin) AS swxx_bldg_area_public_admin,
        SUM(w * bldg_sqft_public_admin * bldg_sqft_public_admin) AS swyy_bldg_area_public_admin,
        SUM(w * bldg_area_public_admin * bldg_sqft_public_admin) AS swxy_bldg_area_public_admin,
        -- bldg_area_education
        SUM(w * bldg_area_education) AS swx_bldg_area_education,
        SUM(w * bldg_sqft_education) AS swy_bldg_area_education,
        SUM(w * bldg_area_education * bldg_area_education) AS swxx_bldg_area_education,
        SUM(w * bldg_sqft_education * bldg_sqft_education) AS swyy_bldg_area_education,
        SUM(w * bldg_area_education * bldg_sqft_education) AS swxy_bldg_area_education,
        -- bldg_area_medical_services
        SUM(w * bldg_area_medical_services) AS swx_bldg_area_medical_services,
        SUM(w * bldg_sqft_medical_services) AS swy_bldg_area_medical_services,
        SUM(w * bldg_area_medical_services * bldg_area_medical_services) AS swxx_bldg_area_medical_services,
        SUM(w * bldg_sqft_medical_services * bldg_sqft_medical_services) AS swyy_bldg_area_medical_services,
        SUM(w * bldg_area_medical_services * bldg_sqft_medical_services) AS swxy_bldg_area_medical_services,
        -- bldg_area_transport_warehousing
        SUM(w * bldg_area_transport_warehousing) AS swx_bldg_area_transport_warehousing,
        SUM(w * bldg_sqft_transport_warehousing) AS swy_bldg_area_transport_warehousing,
        SUM(w * bldg_area_transport_warehousing * bldg_area_transport_warehousing) AS swxx_bldg_area_transport_warehousing,
        SUM(w * bldg_sqft_transport_warehousing * bldg_sqft_transport_warehousing) AS swyy_bldg_area_transport_warehousing,
        SUM(w * bldg_area_transport_warehousing * bldg_sqft_transport_warehousing) AS swxy_bldg_area_transport_warehousing,
        -- bldg_area_wholesale
        SUM(w * bldg_area_wholesale) AS swx_bldg_area_wholesale,
        SUM(w * bldg_sqft_wholesale) AS swy_bldg_area_wholesale,
        SUM(w * bldg_area_wholesale * bldg_area_wholesale) AS swxx_bldg_area_wholesale,
        SUM(w * bldg_sqft_wholesale * bldg_sqft_wholesale) AS swyy_bldg_area_wholesale,
        SUM(w * bldg_area_wholesale * bldg_sqft_wholesale) AS swxy_bldg_area_wholesale,
        -- residential_irrigated_area
        SUM(w * residential_irrigated_area) AS swx_residential_irrigated_area,
        SUM(w * residential_irrigated_sqft) AS swy_residential_irrigated_area,
        SUM(w * residential_irrigated_area * residential_irrigated_area) AS swxx_residential_irrigated_area,
        SUM(w * residential_irrigated_sqft * residential_irrigated_sqft) AS swyy_residential_irrigated_area,
        SUM(w * residential_irrigated_area * residential_irrigated_sqft) AS swxy_residential_irrigated_area,
        -- commercial_irrigated_area
        SUM(w * commercial_irrigated_area) AS swx_commercial_irrigated_area,
        SUM(w * commercial_irrigated_sqft) AS swy_commercial_irrigated_area,
        SUM(w * commercial_irrigated_area * commercial_irrigated_area) AS swxx_commercial_irrigated_area,
        SUM(w * commercial_irrigated_sqft * commercial_irrigated_sqft) AS swyy_commercial_irrigated_area,
        SUM(w * commercial_irrigated_area * commercial_irrigated_sqft) AS swxy_commercial_irrigated_area
    FROM base
)

SELECT
    -- area_gross
    (sw * swxy_area_gross - swx_area_gross * swy_area_gross) / NULLIF(
        SQRT((sw * swxx_area_gross - swx_area_gross * swx_area_gross)
           * (sw * swyy_area_gross - swy_area_gross * swy_area_gross)), 0
    ) AS area_gross,
    -- area_parcel
    (sw * swxy_area_parcel - swx_area_parcel * swy_area_parcel) / NULLIF(
        SQRT((sw * swxx_area_parcel - swx_area_parcel * swx_area_parcel)
           * (sw * swyy_area_parcel - swy_area_parcel * swy_area_parcel)), 0
    ) AS area_parcel,
    -- area_parcel_res_detsf
    (sw * swxy_area_parcel_res_detsf - swx_area_parcel_res_detsf * swy_area_parcel_res_detsf) / NULLIF(
        SQRT((sw * swxx_area_parcel_res_detsf - swx_area_parcel_res_detsf * swx_area_parcel_res_detsf)
           * (sw * swyy_area_parcel_res_detsf - swy_area_parcel_res_detsf * swy_area_parcel_res_detsf)), 0
    ) AS area_parcel_res_detsf,
    -- area_parcel_res_detsf_sl
    (sw * swxy_area_parcel_res_detsf_sl - swx_area_parcel_res_detsf_sl * swy_area_parcel_res_detsf_sl) / NULLIF(
        SQRT((sw * swxx_area_parcel_res_detsf_sl - swx_area_parcel_res_detsf_sl * swx_area_parcel_res_detsf_sl)
           * (sw * swyy_area_parcel_res_detsf_sl - swy_area_parcel_res_detsf_sl * swy_area_parcel_res_detsf_sl)), 0
    ) AS area_parcel_res_detsf_sl,
    -- area_parcel_res_detsf_ll
    (sw * swxy_area_parcel_res_detsf_ll - swx_area_parcel_res_detsf_ll * swy_area_parcel_res_detsf_ll) / NULLIF(
        SQRT((sw * swxx_area_parcel_res_detsf_ll - swx_area_parcel_res_detsf_ll * swx_area_parcel_res_detsf_ll)
           * (sw * swyy_area_parcel_res_detsf_ll - swy_area_parcel_res_detsf_ll * swy_area_parcel_res_detsf_ll)), 0
    ) AS area_parcel_res_detsf_ll,
    -- area_parcel_res_attsf
    (sw * swxy_area_parcel_res_attsf - swx_area_parcel_res_attsf * swy_area_parcel_res_attsf) / NULLIF(
        SQRT((sw * swxx_area_parcel_res_attsf - swx_area_parcel_res_attsf * swx_area_parcel_res_attsf)
           * (sw * swyy_area_parcel_res_attsf - swy_area_parcel_res_attsf * swy_area_parcel_res_attsf)), 0
    ) AS area_parcel_res_attsf,
    -- area_parcel_res_mf
    (sw * swxy_area_parcel_res_mf - swx_area_parcel_res_mf * swy_area_parcel_res_mf) / NULLIF(
        SQRT((sw * swxx_area_parcel_res_mf - swx_area_parcel_res_mf * swx_area_parcel_res_mf)
           * (sw * swyy_area_parcel_res_mf - swy_area_parcel_res_mf * swy_area_parcel_res_mf)), 0
    ) AS area_parcel_res_mf,
    -- area_parcel_res
    (sw * swxy_area_parcel_res - swx_area_parcel_res * swy_area_parcel_res) / NULLIF(
        SQRT((sw * swxx_area_parcel_res - swx_area_parcel_res * swx_area_parcel_res)
           * (sw * swyy_area_parcel_res - swy_area_parcel_res * swy_area_parcel_res)), 0
    ) AS area_parcel_res,
    -- area_parcel_emp
    (sw * swxy_area_parcel_emp - swx_area_parcel_emp * swy_area_parcel_emp) / NULLIF(
        SQRT((sw * swxx_area_parcel_emp - swx_area_parcel_emp * swx_area_parcel_emp)
           * (sw * swyy_area_parcel_emp - swy_area_parcel_emp * swy_area_parcel_emp)), 0
    ) AS area_parcel_emp,
    -- area_parcel_emp_ret
    (sw * swxy_area_parcel_emp_ret - swx_area_parcel_emp_ret * swy_area_parcel_emp_ret) / NULLIF(
        SQRT((sw * swxx_area_parcel_emp_ret - swx_area_parcel_emp_ret * swx_area_parcel_emp_ret)
           * (sw * swyy_area_parcel_emp_ret - swy_area_parcel_emp_ret * swy_area_parcel_emp_ret)), 0
    ) AS area_parcel_emp_ret,
    -- area_parcel_emp_off
    (sw * swxy_area_parcel_emp_off - swx_area_parcel_emp_off * swy_area_parcel_emp_off) / NULLIF(
        SQRT((sw * swxx_area_parcel_emp_off - swx_area_parcel_emp_off * swx_area_parcel_emp_off)
           * (sw * swyy_area_parcel_emp_off - swy_area_parcel_emp_off * swy_area_parcel_emp_off)), 0
    ) AS area_parcel_emp_off,
    -- area_parcel_emp_pub
    (sw * swxy_area_parcel_emp_pub - swx_area_parcel_emp_pub * swy_area_parcel_emp_pub) / NULLIF(
        SQRT((sw * swxx_area_parcel_emp_pub - swx_area_parcel_emp_pub * swx_area_parcel_emp_pub)
           * (sw * swyy_area_parcel_emp_pub - swy_area_parcel_emp_pub * swy_area_parcel_emp_pub)), 0
    ) AS area_parcel_emp_pub,
    -- area_parcel_emp_ind
    (sw * swxy_area_parcel_emp_ind - swx_area_parcel_emp_ind * swy_area_parcel_emp_ind) / NULLIF(
        SQRT((sw * swxx_area_parcel_emp_ind - swx_area_parcel_emp_ind * swx_area_parcel_emp_ind)
           * (sw * swyy_area_parcel_emp_ind - swy_area_parcel_emp_ind * swy_area_parcel_emp_ind)), 0
    ) AS area_parcel_emp_ind,
    -- area_parcel_emp_ag
    (sw * swxy_area_parcel_emp_ag - swx_area_parcel_emp_ag * swy_area_parcel_emp_ag) / NULLIF(
        SQRT((sw * swxx_area_parcel_emp_ag - swx_area_parcel_emp_ag * swx_area_parcel_emp_ag)
           * (sw * swyy_area_parcel_emp_ag - swy_area_parcel_emp_ag * swy_area_parcel_emp_ag)), 0
    ) AS area_parcel_emp_ag,
    -- area_parcel_emp_military
    (sw * swxy_area_parcel_emp_military - swx_area_parcel_emp_military * swy_area_parcel_emp_military) / NULLIF(
        SQRT((sw * swxx_area_parcel_emp_military - swx_area_parcel_emp_military * swx_area_parcel_emp_military)
           * (sw * swyy_area_parcel_emp_military - swy_area_parcel_emp_military * swy_area_parcel_emp_military)), 0
    ) AS area_parcel_emp_military,
    -- area_parcel_mixed_use
    (sw * swxy_area_parcel_mixed_use - swx_area_parcel_mixed_use * swy_area_parcel_mixed_use) / NULLIF(
        SQRT((sw * swxx_area_parcel_mixed_use - swx_area_parcel_mixed_use * swx_area_parcel_mixed_use)
           * (sw * swyy_area_parcel_mixed_use - swy_area_parcel_mixed_use * swy_area_parcel_mixed_use)), 0
    ) AS area_parcel_mixed_use,
    -- area_parcel_no_use
    (sw * swxy_area_parcel_no_use - swx_area_parcel_no_use * swy_area_parcel_no_use) / NULLIF(
        SQRT((sw * swxx_area_parcel_no_use - swx_area_parcel_no_use * swx_area_parcel_no_use)
           * (sw * swyy_area_parcel_no_use - swy_area_parcel_no_use * swy_area_parcel_no_use)), 0
    ) AS area_parcel_no_use,
    -- intersection_density
    (sw * swxy_intersection_density - swx_intersection_density * swy_intersection_density) / NULLIF(
        SQRT((sw * swxx_intersection_density - swx_intersection_density * swx_intersection_density)
           * (sw * swyy_intersection_density - swy_intersection_density * swy_intersection_density)), 0
    ) AS intersection_density,
    -- pop
    (sw * swxy_pop - swx_pop * swy_pop) / NULLIF(
        SQRT((sw * swxx_pop - swx_pop * swx_pop)
           * (sw * swyy_pop - swy_pop * swy_pop)), 0
    ) AS pop,
    -- hh
    (sw * swxy_hh - swx_hh * swy_hh) / NULLIF(
        SQRT((sw * swxx_hh - swx_hh * swx_hh)
           * (sw * swyy_hh - swy_hh * swy_hh)), 0
    ) AS hh,
    -- du
    (sw * swxy_du - swx_du * swy_du) / NULLIF(
        SQRT((sw * swxx_du - swx_du * swx_du)
           * (sw * swyy_du - swy_du * swy_du)), 0
    ) AS du,
    -- du_detsf
    (sw * swxy_du_detsf - swx_du_detsf * swy_du_detsf) / NULLIF(
        SQRT((sw * swxx_du_detsf - swx_du_detsf * swx_du_detsf)
           * (sw * swyy_du_detsf - swy_du_detsf * swy_du_detsf)), 0
    ) AS du_detsf,
    -- du_detsf_sl
    (sw * swxy_du_detsf_sl - swx_du_detsf_sl * swy_du_detsf_sl) / NULLIF(
        SQRT((sw * swxx_du_detsf_sl - swx_du_detsf_sl * swx_du_detsf_sl)
           * (sw * swyy_du_detsf_sl - swy_du_detsf_sl * swy_du_detsf_sl)), 0
    ) AS du_detsf_sl,
    -- du_detsf_ll
    (sw * swxy_du_detsf_ll - swx_du_detsf_ll * swy_du_detsf_ll) / NULLIF(
        SQRT((sw * swxx_du_detsf_ll - swx_du_detsf_ll * swx_du_detsf_ll)
           * (sw * swyy_du_detsf_ll - swy_du_detsf_ll * swy_du_detsf_ll)), 0
    ) AS du_detsf_ll,
    -- du_attsf
    (sw * swxy_du_attsf - swx_du_attsf * swy_du_attsf) / NULLIF(
        SQRT((sw * swxx_du_attsf - swx_du_attsf * swx_du_attsf)
           * (sw * swyy_du_attsf - swy_du_attsf * swy_du_attsf)), 0
    ) AS du_attsf,
    -- du_mf
    (sw * swxy_du_mf - swx_du_mf * swy_du_mf) / NULLIF(
        SQRT((sw * swxx_du_mf - swx_du_mf * swx_du_mf)
           * (sw * swyy_du_mf - swy_du_mf * swy_du_mf)), 0
    ) AS du_mf,
    -- du_mf2to4
    (sw * swxy_du_mf2to4 - swx_du_mf2to4 * swy_du_mf2to4) / NULLIF(
        SQRT((sw * swxx_du_mf2to4 - swx_du_mf2to4 * swx_du_mf2to4)
           * (sw * swyy_du_mf2to4 - swy_du_mf2to4 * swy_du_mf2to4)), 0
    ) AS du_mf2to4,
    -- du_mf5p
    (sw * swxy_du_mf5p - swx_du_mf5p * swy_du_mf5p) / NULLIF(
        SQRT((sw * swxx_du_mf5p - swx_du_mf5p * swx_du_mf5p)
           * (sw * swyy_du_mf5p - swy_du_mf5p * swy_du_mf5p)), 0
    ) AS du_mf5p,
    -- emp
    (sw * swxy_emp - swx_emp * swy_emp) / NULLIF(
        SQRT((sw * swxx_emp - swx_emp * swx_emp)
           * (sw * swyy_emp - swy_emp * swy_emp)), 0
    ) AS emp,
    -- emp_ret
    (sw * swxy_emp_ret - swx_emp_ret * swy_emp_ret) / NULLIF(
        SQRT((sw * swxx_emp_ret - swx_emp_ret * swx_emp_ret)
           * (sw * swyy_emp_ret - swy_emp_ret * swy_emp_ret)), 0
    ) AS emp_ret,
    -- emp_retail_services
    (sw * swxy_emp_retail_services - swx_emp_retail_services * swy_emp_retail_services) / NULLIF(
        SQRT((sw * swxx_emp_retail_services - swx_emp_retail_services * swx_emp_retail_services)
           * (sw * swyy_emp_retail_services - swy_emp_retail_services * swy_emp_retail_services)), 0
    ) AS emp_retail_services,
    -- emp_restaurant
    (sw * swxy_emp_restaurant - swx_emp_restaurant * swy_emp_restaurant) / NULLIF(
        SQRT((sw * swxx_emp_restaurant - swx_emp_restaurant * swx_emp_restaurant)
           * (sw * swyy_emp_restaurant - swy_emp_restaurant * swy_emp_restaurant)), 0
    ) AS emp_restaurant,
    -- emp_accommodation
    (sw * swxy_emp_accommodation - swx_emp_accommodation * swy_emp_accommodation) / NULLIF(
        SQRT((sw * swxx_emp_accommodation - swx_emp_accommodation * swx_emp_accommodation)
           * (sw * swyy_emp_accommodation - swy_emp_accommodation * swy_emp_accommodation)), 0
    ) AS emp_accommodation,
    -- emp_arts_entertainment
    (sw * swxy_emp_arts_entertainment - swx_emp_arts_entertainment * swy_emp_arts_entertainment) / NULLIF(
        SQRT((sw * swxx_emp_arts_entertainment - swx_emp_arts_entertainment * swx_emp_arts_entertainment)
           * (sw * swyy_emp_arts_entertainment - swy_emp_arts_entertainment * swy_emp_arts_entertainment)), 0
    ) AS emp_arts_entertainment,
    -- emp_other_services
    (sw * swxy_emp_other_services - swx_emp_other_services * swy_emp_other_services) / NULLIF(
        SQRT((sw * swxx_emp_other_services - swx_emp_other_services * swx_emp_other_services)
           * (sw * swyy_emp_other_services - swy_emp_other_services * swy_emp_other_services)), 0
    ) AS emp_other_services,
    -- emp_off
    (sw * swxy_emp_off - swx_emp_off * swy_emp_off) / NULLIF(
        SQRT((sw * swxx_emp_off - swx_emp_off * swx_emp_off)
           * (sw * swyy_emp_off - swy_emp_off * swy_emp_off)), 0
    ) AS emp_off,
    -- emp_office_services
    (sw * swxy_emp_office_services - swx_emp_office_services * swy_emp_office_services) / NULLIF(
        SQRT((sw * swxx_emp_office_services - swx_emp_office_services * swx_emp_office_services)
           * (sw * swyy_emp_office_services - swy_emp_office_services * swy_emp_office_services)), 0
    ) AS emp_office_services,
    -- emp_medical_services
    (sw * swxy_emp_medical_services - swx_emp_medical_services * swy_emp_medical_services) / NULLIF(
        SQRT((sw * swxx_emp_medical_services - swx_emp_medical_services * swx_emp_medical_services)
           * (sw * swyy_emp_medical_services - swy_emp_medical_services * swy_emp_medical_services)), 0
    ) AS emp_medical_services,
    -- emp_pub
    (sw * swxy_emp_pub - swx_emp_pub * swy_emp_pub) / NULLIF(
        SQRT((sw * swxx_emp_pub - swx_emp_pub * swx_emp_pub)
           * (sw * swyy_emp_pub - swy_emp_pub * swy_emp_pub)), 0
    ) AS emp_pub,
    -- emp_public_admin
    (sw * swxy_emp_public_admin - swx_emp_public_admin * swy_emp_public_admin) / NULLIF(
        SQRT((sw * swxx_emp_public_admin - swx_emp_public_admin * swx_emp_public_admin)
           * (sw * swyy_emp_public_admin - swy_emp_public_admin * swy_emp_public_admin)), 0
    ) AS emp_public_admin,
    -- emp_education
    (sw * swxy_emp_education - swx_emp_education * swy_emp_education) / NULLIF(
        SQRT((sw * swxx_emp_education - swx_emp_education * swx_emp_education)
           * (sw * swyy_emp_education - swy_emp_education * swy_emp_education)), 0
    ) AS emp_education,
    -- emp_ind
    (sw * swxy_emp_ind - swx_emp_ind * swy_emp_ind) / NULLIF(
        SQRT((sw * swxx_emp_ind - swx_emp_ind * swx_emp_ind)
           * (sw * swyy_emp_ind - swy_emp_ind * swy_emp_ind)), 0
    ) AS emp_ind,
    -- emp_manufacturing
    (sw * swxy_emp_manufacturing - swx_emp_manufacturing * swy_emp_manufacturing) / NULLIF(
        SQRT((sw * swxx_emp_manufacturing - swx_emp_manufacturing * swx_emp_manufacturing)
           * (sw * swyy_emp_manufacturing - swy_emp_manufacturing * swy_emp_manufacturing)), 0
    ) AS emp_manufacturing,
    -- emp_wholesale
    (sw * swxy_emp_wholesale - swx_emp_wholesale * swy_emp_wholesale) / NULLIF(
        SQRT((sw * swxx_emp_wholesale - swx_emp_wholesale * swx_emp_wholesale)
           * (sw * swyy_emp_wholesale - swy_emp_wholesale * swy_emp_wholesale)), 0
    ) AS emp_wholesale,
    -- emp_transport_warehousing
    (sw * swxy_emp_transport_warehousing - swx_emp_transport_warehousing * swy_emp_transport_warehousing) / NULLIF(
        SQRT((sw * swxx_emp_transport_warehousing - swx_emp_transport_warehousing * swx_emp_transport_warehousing)
           * (sw * swyy_emp_transport_warehousing - swy_emp_transport_warehousing * swy_emp_transport_warehousing)), 0
    ) AS emp_transport_warehousing,
    -- emp_utilities
    (sw * swxy_emp_utilities - swx_emp_utilities * swy_emp_utilities) / NULLIF(
        SQRT((sw * swxx_emp_utilities - swx_emp_utilities * swx_emp_utilities)
           * (sw * swyy_emp_utilities - swy_emp_utilities * swy_emp_utilities)), 0
    ) AS emp_utilities,
    -- emp_construction
    (sw * swxy_emp_construction - swx_emp_construction * swy_emp_construction) / NULLIF(
        SQRT((sw * swxx_emp_construction - swx_emp_construction * swx_emp_construction)
           * (sw * swyy_emp_construction - swy_emp_construction * swy_emp_construction)), 0
    ) AS emp_construction,
    -- emp_ag
    (sw * swxy_emp_ag - swx_emp_ag * swy_emp_ag) / NULLIF(
        SQRT((sw * swxx_emp_ag - swx_emp_ag * swx_emp_ag)
           * (sw * swyy_emp_ag - swy_emp_ag * swy_emp_ag)), 0
    ) AS emp_ag,
    -- emp_agriculture
    (sw * swxy_emp_agriculture - swx_emp_agriculture * swy_emp_agriculture) / NULLIF(
        SQRT((sw * swxx_emp_agriculture - swx_emp_agriculture * swx_emp_agriculture)
           * (sw * swyy_emp_agriculture - swy_emp_agriculture * swy_emp_agriculture)), 0
    ) AS emp_agriculture,
    -- emp_extraction
    (sw * swxy_emp_extraction - swx_emp_extraction * swy_emp_extraction) / NULLIF(
        SQRT((sw * swxx_emp_extraction - swx_emp_extraction * swx_emp_extraction)
           * (sw * swyy_emp_extraction - swy_emp_extraction * swy_emp_extraction)), 0
    ) AS emp_extraction,
    -- emp_military
    (sw * swxy_emp_military - swx_emp_military * swy_emp_military) / NULLIF(
        SQRT((sw * swxx_emp_military - swx_emp_military * swx_emp_military)
           * (sw * swyy_emp_military - swy_emp_military * swy_emp_military)), 0
    ) AS emp_military,
    -- bldg_area_detsf_sl
    (sw * swxy_bldg_area_detsf_sl - swx_bldg_area_detsf_sl * swy_bldg_area_detsf_sl) / NULLIF(
        SQRT((sw * swxx_bldg_area_detsf_sl - swx_bldg_area_detsf_sl * swx_bldg_area_detsf_sl)
           * (sw * swyy_bldg_area_detsf_sl - swy_bldg_area_detsf_sl * swy_bldg_area_detsf_sl)), 0
    ) AS bldg_area_detsf_sl,
    -- bldg_area_detsf_ll
    (sw * swxy_bldg_area_detsf_ll - swx_bldg_area_detsf_ll * swy_bldg_area_detsf_ll) / NULLIF(
        SQRT((sw * swxx_bldg_area_detsf_ll - swx_bldg_area_detsf_ll * swx_bldg_area_detsf_ll)
           * (sw * swyy_bldg_area_detsf_ll - swy_bldg_area_detsf_ll * swy_bldg_area_detsf_ll)), 0
    ) AS bldg_area_detsf_ll,
    -- bldg_area_attsf
    (sw * swxy_bldg_area_attsf - swx_bldg_area_attsf * swy_bldg_area_attsf) / NULLIF(
        SQRT((sw * swxx_bldg_area_attsf - swx_bldg_area_attsf * swx_bldg_area_attsf)
           * (sw * swyy_bldg_area_attsf - swy_bldg_area_attsf * swy_bldg_area_attsf)), 0
    ) AS bldg_area_attsf,
    -- bldg_area_mf
    (sw * swxy_bldg_area_mf - swx_bldg_area_mf * swy_bldg_area_mf) / NULLIF(
        SQRT((sw * swxx_bldg_area_mf - swx_bldg_area_mf * swx_bldg_area_mf)
           * (sw * swyy_bldg_area_mf - swy_bldg_area_mf * swy_bldg_area_mf)), 0
    ) AS bldg_area_mf,
    -- bldg_area_retail_services
    (sw * swxy_bldg_area_retail_services - swx_bldg_area_retail_services * swy_bldg_area_retail_services) / NULLIF(
        SQRT((sw * swxx_bldg_area_retail_services - swx_bldg_area_retail_services * swx_bldg_area_retail_services)
           * (sw * swyy_bldg_area_retail_services - swy_bldg_area_retail_services * swy_bldg_area_retail_services)), 0
    ) AS bldg_area_retail_services,
    -- bldg_area_restaurant
    (sw * swxy_bldg_area_restaurant - swx_bldg_area_restaurant * swy_bldg_area_restaurant) / NULLIF(
        SQRT((sw * swxx_bldg_area_restaurant - swx_bldg_area_restaurant * swx_bldg_area_restaurant)
           * (sw * swyy_bldg_area_restaurant - swy_bldg_area_restaurant * swy_bldg_area_restaurant)), 0
    ) AS bldg_area_restaurant,
    -- bldg_area_accommodation
    (sw * swxy_bldg_area_accommodation - swx_bldg_area_accommodation * swy_bldg_area_accommodation) / NULLIF(
        SQRT((sw * swxx_bldg_area_accommodation - swx_bldg_area_accommodation * swx_bldg_area_accommodation)
           * (sw * swyy_bldg_area_accommodation - swy_bldg_area_accommodation * swy_bldg_area_accommodation)), 0
    ) AS bldg_area_accommodation,
    -- bldg_area_arts_entertainment
    (sw * swxy_bldg_area_arts_entertainment - swx_bldg_area_arts_entertainment * swy_bldg_area_arts_entertainment) / NULLIF(
        SQRT((sw * swxx_bldg_area_arts_entertainment - swx_bldg_area_arts_entertainment * swx_bldg_area_arts_entertainment)
           * (sw * swyy_bldg_area_arts_entertainment - swy_bldg_area_arts_entertainment * swy_bldg_area_arts_entertainment)), 0
    ) AS bldg_area_arts_entertainment,
    -- bldg_area_other_services
    (sw * swxy_bldg_area_other_services - swx_bldg_area_other_services * swy_bldg_area_other_services) / NULLIF(
        SQRT((sw * swxx_bldg_area_other_services - swx_bldg_area_other_services * swx_bldg_area_other_services)
           * (sw * swyy_bldg_area_other_services - swy_bldg_area_other_services * swy_bldg_area_other_services)), 0
    ) AS bldg_area_other_services,
    -- bldg_area_office_services
    (sw * swxy_bldg_area_office_services - swx_bldg_area_office_services * swy_bldg_area_office_services) / NULLIF(
        SQRT((sw * swxx_bldg_area_office_services - swx_bldg_area_office_services * swx_bldg_area_office_services)
           * (sw * swyy_bldg_area_office_services - swy_bldg_area_office_services * swy_bldg_area_office_services)), 0
    ) AS bldg_area_office_services,
    -- bldg_area_public_admin
    (sw * swxy_bldg_area_public_admin - swx_bldg_area_public_admin * swy_bldg_area_public_admin) / NULLIF(
        SQRT((sw * swxx_bldg_area_public_admin - swx_bldg_area_public_admin * swx_bldg_area_public_admin)
           * (sw * swyy_bldg_area_public_admin - swy_bldg_area_public_admin * swy_bldg_area_public_admin)), 0
    ) AS bldg_area_public_admin,
    -- bldg_area_education
    (sw * swxy_bldg_area_education - swx_bldg_area_education * swy_bldg_area_education) / NULLIF(
        SQRT((sw * swxx_bldg_area_education - swx_bldg_area_education * swx_bldg_area_education)
           * (sw * swyy_bldg_area_education - swy_bldg_area_education * swy_bldg_area_education)), 0
    ) AS bldg_area_education,
    -- bldg_area_medical_services
    (sw * swxy_bldg_area_medical_services - swx_bldg_area_medical_services * swy_bldg_area_medical_services) / NULLIF(
        SQRT((sw * swxx_bldg_area_medical_services - swx_bldg_area_medical_services * swx_bldg_area_medical_services)
           * (sw * swyy_bldg_area_medical_services - swy_bldg_area_medical_services * swy_bldg_area_medical_services)), 0
    ) AS bldg_area_medical_services,
    -- bldg_area_transport_warehousing
    (sw * swxy_bldg_area_transport_warehousing - swx_bldg_area_transport_warehousing * swy_bldg_area_transport_warehousing) / NULLIF(
        SQRT((sw * swxx_bldg_area_transport_warehousing - swx_bldg_area_transport_warehousing * swx_bldg_area_transport_warehousing)
           * (sw * swyy_bldg_area_transport_warehousing - swy_bldg_area_transport_warehousing * swy_bldg_area_transport_warehousing)), 0
    ) AS bldg_area_transport_warehousing,
    -- bldg_area_wholesale
    (sw * swxy_bldg_area_wholesale - swx_bldg_area_wholesale * swy_bldg_area_wholesale) / NULLIF(
        SQRT((sw * swxx_bldg_area_wholesale - swx_bldg_area_wholesale * swx_bldg_area_wholesale)
           * (sw * swyy_bldg_area_wholesale - swy_bldg_area_wholesale * swy_bldg_area_wholesale)), 0
    ) AS bldg_area_wholesale,
    -- residential_irrigated_area
    (sw * swxy_residential_irrigated_area - swx_residential_irrigated_area * swy_residential_irrigated_area) / NULLIF(
        SQRT((sw * swxx_residential_irrigated_area - swx_residential_irrigated_area * swx_residential_irrigated_area)
           * (sw * swyy_residential_irrigated_area - swy_residential_irrigated_area * swy_residential_irrigated_area)), 0
    ) AS residential_irrigated_area,
    -- commercial_irrigated_area
    (sw * swxy_commercial_irrigated_area - swx_commercial_irrigated_area * swy_commercial_irrigated_area) / NULLIF(
        SQRT((sw * swxx_commercial_irrigated_area - swx_commercial_irrigated_area * swx_commercial_irrigated_area)
           * (sw * swyy_commercial_irrigated_area - swy_commercial_irrigated_area * swy_commercial_irrigated_area)), 0
    ) AS commercial_irrigated_area
FROM stats
