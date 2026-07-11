MODEL (
  name brewgis.assessor.parcel_dasymetric_weights,
  kind INCREMENTAL_BY_UNIQUE_KEY (
    unique_key (apn),
    batch_size 100000
  ),
  audits (
    assert_pop_dasym_weight_not_null,
    assert_pop_dasym_weight_non_negative,
    assert_emp_dasym_weight_non_negative,
    assert_emp_dasym_weight_fallback
  )
);

-- Dasymetric Weights — lightweight weight computation only.
--
-- Reads parcel features directly from assessor parcels, sales, and building
-- tables, then computes pop/emp dasymetric weights with simple COALESCE +
-- multiplier expressions (~7M query cost).
--
-- Split from the original 18-CTE model to allow independent
-- incremental rebuilds: when authoritative_residential_area changes,
-- only this model (~30min) needs to rebuild instead of the full 5h.

WITH parcel_features AS (
    SELECT
        ap.apn,
        ap.landuse,
        ap.lot_size_acres,
        ap.zone,
        COALESCE(ap.land_development_category, 'urban') AS land_development_category,
        COALESCE(sd.actual_living_sqft, 0)::double precision AS actual_living_sqft,
        COALESCE(sd.actual_building_sqft, 0)::double precision AS actual_building_sqft,
        sd.property_type,
        sd.sales_lot_size_acres,
        sd.units,
        COALESCE(bs.residential_building_sqft, 0)::double precision AS residential_building_sqft,
        COALESCE(bs.commercial_building_sqft, 0)::double precision AS commercial_building_sqft,
        COALESCE(bs.industrial_building_sqft, 0)::double precision AS industrial_building_sqft,
        COALESCE(bs.other_building_sqft, 0)::double precision AS other_building_sqft,
        COALESCE(bs.total_footprint_sqft, 0)::double precision AS total_footprint_sqft,
        COALESCE(bs.building_count, 0)::integer AS building_count,
        COALESCE(bs.footprint_ratio, 0)::double precision AS footprint_ratio,
        COALESCE(bs.max_levels, 0)::integer AS max_levels,
        COALESCE(id.intersection_density, 0)::double precision AS intersection_density,
        COALESCE(dr.du_detsf_sl, 0)::double precision AS du_detsf_sl_regressor,
        COALESCE(dr.du_detsf_ll, 0)::double precision AS du_detsf_ll_regressor,
        COALESCE(dr.du_attsf, 0)::double precision AS du_attsf_regressor,
        COALESCE(dr.du_mf2to4, 0)::double precision AS du_mf2to4_regressor,
        COALESCE(dr.du_mf5p, 0)::double precision AS du_mf5p_regressor,
        COALESCE(dr.du_total, 0)::double precision AS du_total_regressor,
        COALESCE(sr.bldg_sqft_detsf_sl, 0)::double precision AS bldg_sqft_detsf_sl_regressor,
        COALESCE(sr.bldg_sqft_detsf_ll, 0)::double precision AS bldg_sqft_detsf_ll_regressor,
        COALESCE(sr.bldg_sqft_attsf, 0)::double precision AS bldg_sqft_attsf_regressor,
        COALESCE(sr.bldg_sqft_mf, 0)::double precision AS bldg_sqft_mf_regressor,
        COALESCE(sr.bldg_sqft_retail_services, 0)::double precision AS bldg_sqft_retail_services_regressor,
        COALESCE(sr.bldg_sqft_restaurant, 0)::double precision AS bldg_sqft_restaurant_regressor,
        COALESCE(sr.bldg_sqft_accommodation, 0)::double precision AS bldg_sqft_accommodation_regressor,
        COALESCE(sr.bldg_sqft_arts_entertainment, 0)::double precision AS bldg_sqft_arts_entertainment_regressor,
        COALESCE(sr.bldg_sqft_other_services, 0)::double precision AS bldg_sqft_other_services_regressor,
        COALESCE(sr.bldg_sqft_office_services, 0)::double precision AS bldg_sqft_office_services_regressor,
        COALESCE(sr.bldg_sqft_public_admin, 0)::double precision AS bldg_sqft_public_admin_regressor,
        COALESCE(sr.bldg_sqft_education, 0)::double precision AS bldg_sqft_education_regressor,
        COALESCE(sr.bldg_sqft_medical_services, 0)::double precision AS bldg_sqft_medical_services_regressor,
        COALESCE(sr.bldg_sqft_transport_warehousing, 0)::double precision AS bldg_sqft_transport_warehousing_regressor,
        COALESCE(sr.bldg_sqft_wholesale, 0)::double precision AS bldg_sqft_wholesale_regressor
    FROM brewgis.assessor.sacog_assessor_parcels ap
    LEFT JOIN brewgis.assessor.sacog_assessor_sales_deduped sd ON ap.apn = sd.apn
    LEFT JOIN brewgis.assessor.parcel_building_sqft_by_type bs ON ap.apn = bs.apn
    LEFT JOIN brewgis.assessor.overture_intersection_density id ON ap.apn = id.apn
    LEFT JOIN brewgis.assessor.parcel_du_regressor dr ON ap.apn = dr.apn
    LEFT JOIN brewgis.assessor.parcel_sqft_regressor sr ON ap.apn = sr.apn
),

auth_res AS (
    SELECT apn, authoritative_residential_sqft, authoritative_non_residential_sqft
    FROM brewgis.assessor.authoritative_residential_area
)

SELECT
    pf.apn,
    pf.landuse,
    pf.lot_size_acres,
    pf.zone,
    pf.land_development_category,
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
    pf.du_detsf_sl_regressor,
    pf.du_detsf_ll_regressor,
    pf.du_attsf_regressor,
    pf.du_mf2to4_regressor,
    pf.du_mf5p_regressor,
    pf.du_total_regressor,
    pf.bldg_sqft_detsf_sl_regressor,
    pf.bldg_sqft_detsf_ll_regressor,
    pf.bldg_sqft_attsf_regressor,
    pf.bldg_sqft_mf_regressor,
    pf.bldg_sqft_retail_services_regressor,
    pf.bldg_sqft_restaurant_regressor,
    pf.bldg_sqft_accommodation_regressor,
    pf.bldg_sqft_arts_entertainment_regressor,
    pf.bldg_sqft_other_services_regressor,
    pf.bldg_sqft_office_services_regressor,
    pf.bldg_sqft_public_admin_regressor,
    pf.bldg_sqft_education_regressor,
    pf.bldg_sqft_medical_services_regressor,
    pf.bldg_sqft_transport_warehousing_regressor,
    pf.bldg_sqft_wholesale_regressor,
    GREATEST(0, COALESCE(
        ar.authoritative_residential_sqft,
        pf.residential_building_sqft,
        pf.lot_size_acres * 43560 * 0.15
    )) AS pop_dasym_weight,
    GREATEST(0, COALESCE(
        ar.authoritative_non_residential_sqft,
        NULLIF(pf.commercial_building_sqft + pf.industrial_building_sqft + pf.other_building_sqft, 0),
        pf.lot_size_acres * 43560 * 0.1
    )) * (1.0 + COALESCE(pf.intersection_density, 0.0) / 400.0) AS emp_dasym_weight
FROM parcel_features pf
LEFT JOIN auth_res ar ON pf.apn = ar.apn;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_parcel_dasymetric_weights_apn_@snapshot_hash
  ON @this_model USING btree (apn);
  CREATE INDEX IF NOT EXISTS idx_parcel_dasymetric_weights_int_dens_@snapshot_hash
  ON @this_model USING btree (intersection_density);
ANALYZE @this_model;
