MODEL (
  name brewgis.@{region}.parcel_dasymetric_weights,
  kind INCREMENTAL_BY_UNIQUE_KEY (
    unique_key (apn),
    batch_size 100000
  ),
  audits (
    assert_pop_dasym_weight_not_null,
    assert_pop_dasym_weight_non_negative,
    assert_emp_dasym_weight_non_negative,
    assert_emp_dasym_weight_fallback
  ),
  blueprints (
    (region := sacog),
    (region := fresno)
  )
);

-- Dasymetric Weights — lightweight weight computation only.
--
-- Reads parcel features from the region adapters (assessor parcels, sales,
-- building sqft, intersection densities, ResNet PCA) and computes pop/emp
-- dasymetric weights with COALESCE + multiplier expressions.
--
-- Regressor predictions are NOT joined here (that would create a cycle:
-- the regressors read their feature matrix FROM this model). Instead the
-- regressor columns are populated by the region regressors themselves and
-- joined at the comparison_dasymetric / du_estimation stage. Adapters that
-- have no data source (Fresno sales, building sqft, authoritative area,
-- highway/path density) yield zero rows; the LEFT JOINs + COALESCE fall
-- back to lot-size-based weights.

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
        COALESCE(hw.highway_intersection_density, 0)::double precision AS highway_intersection_density,
        COALESCE(pw.path_intersection_density, 0)::double precision AS path_intersection_density,
        -- ResNet PCA features (regressor features; 0 when region lacks imagery)
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
    FROM brewgis.@{region}.assessor_parcels ap
    LEFT JOIN brewgis.@{region}.assessor_sales_deduped sd ON ap.apn = sd.apn
    LEFT JOIN brewgis.@{region}.parcel_building_sqft_by_type bs ON ap.apn = bs.apn
    LEFT JOIN brewgis.@{region}.overture_intersection_density id ON ap.apn = id.apn
    LEFT JOIN brewgis.@{region}.hwy_intersection_density hw ON ap.apn = hw.apn
    LEFT JOIN brewgis.@{region}.path_intersection_density pw ON ap.apn = pw.apn
    LEFT JOIN brewgis.@{region}.parcel_resnet_features rf ON ap.apn = rf.apn
),

auth_res AS (
    SELECT apn, authoritative_residential_sqft, authoritative_non_residential_sqft
    FROM brewgis.@{region}.authoritative_residential_area
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
    pf.highway_intersection_density,
    pf.path_intersection_density,
    -- ResNet PCA features (pass-through for regressor inference)
    pf.pc01, pf.pc02, pf.pc03, pf.pc04, pf.pc05,
    pf.pc06, pf.pc07, pf.pc08, pf.pc09, pf.pc10,
    pf.pc11, pf.pc12, pf.pc13, pf.pc14, pf.pc15,
    pf.pc16, pf.pc17, pf.pc18, pf.pc19, pf.pc20,
    pf.pc21, pf.pc22, pf.pc23, pf.pc24, pf.pc25,
    pf.pc26, pf.pc27, pf.pc28, pf.pc29, pf.pc30,
    pf.pc31, pf.pc32,
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
  CREATE INDEX IF NOT EXISTS idx_@{region}_dasymetric_weights_apn_@snapshot_hash
  ON @this_model USING btree (apn);
  CREATE INDEX IF NOT EXISTS idx_@{region}_dasymetric_weights_int_dens_@snapshot_hash
  ON @this_model USING btree (intersection_density);
  ANALYZE @this_model;
