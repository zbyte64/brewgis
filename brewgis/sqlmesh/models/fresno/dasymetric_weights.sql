MODEL (
  name brewgis.fresno.dasymetric_weights,
  kind INCREMENTAL_BY_UNIQUE_KEY (
    unique_key (apn),
    batch_size 100000
  ),
  audits (
    assert_pop_dasym_weight_non_negative,
    assert_emp_dasym_weight_non_negative
  )
);

-- Fresno Dasymetric Weights — lightweight weight computation from parcel geometry.
--
-- Fresno parcels lack assessor data (landuse, zone, building sqft, intersection
-- density) so all assessor-derived features default to 0 or NULL.  Dasymetric
-- weights fall back to lot-size-based estimation.
--
-- ResNet PCA features are joined from fresno_parcel_resnet_features when
-- available.  Regressor predictions are produced by separate FULL Python models
-- (fresno_du_regressor, fresno_sqft_regressor, fresno_emp_ratios_regressor) and
-- consumed by fresno_comparison_dasymetric downstream — they are NOT joined here
-- to avoid a circular dependency (regressors read features FROM this model).

WITH parcel_features AS (
    SELECT
        ps.parcel_id AS apn,
        'urban'::text AS land_development_category,
        COALESCE(ps.acres, 0)::double precision AS lot_size_acres,
        -- All assessor-derived columns default to 0 / NULL
        0::double precision AS actual_living_sqft,
        0::double precision AS actual_building_sqft,
        NULL::text AS property_type,
        NULL::double precision AS sales_lot_size_acres,
        0::integer AS units,
        0::double precision AS residential_building_sqft,
        0::double precision AS commercial_building_sqft,
        0::double precision AS industrial_building_sqft,
        0::double precision AS other_building_sqft,
        0::double precision AS total_footprint_sqft,
        0::integer AS building_count,
        0::double precision AS footprint_ratio,
        0::integer AS max_levels,
        0::double precision AS intersection_density,
        -- ResNet PCA features (when available)
        COALESCE(rf.pc01, 0)::double precision AS pc01,
        COALESCE(rf.pc02, 0)::double precision AS pc02,
        COALESCE(rf.pc03, 0)::double precision AS pc03,
        COALESCE(rf.pc04, 0)::double precision AS pc04,
        COALESCE(rf.pc05, 0)::double precision AS pc05,
        COALESCE(rf.pc06, 0)::double precision AS pc06,
        COALESCE(rf.pc07, 0)::double precision AS pc07,
        COALESCE(rf.pc08, 0)::double precision AS pc08,
        COALESCE(rf.pc09, 0)::double precision AS pc09,
        COALESCE(rf.pc10, 0)::double precision AS pc10,
        COALESCE(rf.pc11, 0)::double precision AS pc11,
        COALESCE(rf.pc12, 0)::double precision AS pc12,
        COALESCE(rf.pc13, 0)::double precision AS pc13,
        COALESCE(rf.pc14, 0)::double precision AS pc14,
        COALESCE(rf.pc15, 0)::double precision AS pc15,
        COALESCE(rf.pc16, 0)::double precision AS pc16,
        COALESCE(rf.pc17, 0)::double precision AS pc17,
        COALESCE(rf.pc18, 0)::double precision AS pc18,
        COALESCE(rf.pc19, 0)::double precision AS pc19,
        COALESCE(rf.pc20, 0)::double precision AS pc20,
        COALESCE(rf.pc21, 0)::double precision AS pc21,
        COALESCE(rf.pc22, 0)::double precision AS pc22,
        COALESCE(rf.pc23, 0)::double precision AS pc23,
        COALESCE(rf.pc24, 0)::double precision AS pc24,
        COALESCE(rf.pc25, 0)::double precision AS pc25,
        COALESCE(rf.pc26, 0)::double precision AS pc26,
        COALESCE(rf.pc27, 0)::double precision AS pc27,
        COALESCE(rf.pc28, 0)::double precision AS pc28,
        COALESCE(rf.pc29, 0)::double precision AS pc29,
        COALESCE(rf.pc30, 0)::double precision AS pc30,
        COALESCE(rf.pc31, 0)::double precision AS pc31,
        COALESCE(rf.pc32, 0)::double precision AS pc32
    FROM brewgis.fresno.parcel_shim ps
    LEFT JOIN brewgis.fresno.parcel_resnet_features rf
        ON ps.parcel_id = rf.apn
)

SELECT
    pf.apn,
    pf.land_development_category,
    pf.lot_size_acres,
    pf.actual_living_sqft,
    pf.actual_building_sqft,
    pf.property_type,
    pf.sales_lot_size_acres,
    pf.units,
    pf.residential_building_sqft,
    pf.commercial_building_sqft,
    pf.industrial_building_sqft,
    pf.other_building_sqft,
    pf.total_footprint_sqft,
    pf.building_count,
    pf.footprint_ratio,
    pf.max_levels,
    pf.intersection_density,
    -- ResNet PCA features (pass-through for regressor inference)
    pf.pc01, pf.pc02, pf.pc03, pf.pc04, pf.pc05,
    pf.pc06, pf.pc07, pf.pc08, pf.pc09, pf.pc10,
    pf.pc11, pf.pc12, pf.pc13, pf.pc14, pf.pc15,
    pf.pc16, pf.pc17, pf.pc18, pf.pc19, pf.pc20,
    pf.pc21, pf.pc22, pf.pc23, pf.pc24, pf.pc25,
    pf.pc26, pf.pc27, pf.pc28, pf.pc29, pf.pc30,
    pf.pc31, pf.pc32,
    -- Regressor prediction columns (default 0; populated by regressor FULL models)
    0::double precision AS du_detsf_sl_regressor,
    0::double precision AS du_detsf_ll_regressor,
    0::double precision AS du_attsf_regressor,
    0::double precision AS du_mf2to4_regressor,
    0::double precision AS du_mf5p_regressor,
    0::double precision AS du_total_regressor,
    0::double precision AS bldg_sqft_detsf_sl_regressor,
    0::double precision AS bldg_sqft_detsf_ll_regressor,
    0::double precision AS bldg_sqft_attsf_regressor,
    0::double precision AS bldg_sqft_mf_regressor,
    0::double precision AS bldg_sqft_retail_services_regressor,
    0::double precision AS bldg_sqft_restaurant_regressor,
    0::double precision AS bldg_sqft_accommodation_regressor,
    0::double precision AS bldg_sqft_arts_entertainment_regressor,
    0::double precision AS bldg_sqft_other_services_regressor,
    0::double precision AS bldg_sqft_office_services_regressor,
    0::double precision AS bldg_sqft_public_admin_regressor,
    0::double precision AS bldg_sqft_education_regressor,
    0::double precision AS bldg_sqft_medical_services_regressor,
    0::double precision AS bldg_sqft_transport_warehousing_regressor,
    0::double precision AS bldg_sqft_wholesale_regressor,
    0::double precision AS emp_ret_per_acre_regressor,
    0::double precision AS emp_off_per_acre_regressor,
    0::double precision AS emp_pub_per_acre_regressor,
    0::double precision AS emp_ind_per_acre_regressor,
    0::double precision AS emp_ag_per_acre_regressor,
    -- Dasymetric weights (lot-size fallback — no assessor building sqft available)
    GREATEST(0, COALESCE(pf.lot_size_acres * 43560 * 0.15, 0))::double precision AS pop_dasym_weight,
    GREATEST(0, COALESCE(pf.lot_size_acres * 43560 * 0.1, 0))::double precision AS emp_dasym_weight
FROM parcel_features pf;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_fresno_dasymetric_weights_apn_@snapshot_hash
  ON @this_model USING btree (apn);
ANALYZE @this_model;
