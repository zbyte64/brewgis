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
        COALESCE(id.intersection_density, 0)::double precision AS intersection_density
    FROM brewgis.assessor.sacog_assessor_parcels ap
    LEFT JOIN brewgis.assessor.sacog_assessor_sales_deduped sd ON ap.apn = sd.apn
    LEFT JOIN brewgis.assessor.parcel_building_sqft_by_type bs ON ap.apn = bs.apn
    LEFT JOIN brewgis.assessor.overture_intersection_density id ON ap.apn = id.apn
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
