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
-- Reads pre-computed classification from parcel_bft_classification
-- (where the expensive 6-tier KNN logic lives) and authoritative
-- residential area, then computes pop/emp dasymetric weights with
-- simple COALESCE + multiplier expressions (~7M query cost).
--
-- Split from the original 18-CTE model to allow independent
-- incremental rebuilds: when authoritative_residential_area changes,
-- only this model (~30min) needs to rebuild instead of the full 5h.

WITH classification AS (
    SELECT
        apn,
        built_form_key,
        built_form_key_source,
        du_subtype,
        is_residential,
        landuse,
        lot_size_acres,
        zone,
        land_development_category,
        actual_living_sqft,
        actual_building_sqft,
        property_type,
        sales_lot_size_acres,
        units,
        residential_building_sqft,
        commercial_building_sqft,
        industrial_building_sqft,
        other_building_sqft,
        total_footprint_sqft,
        building_count,
        footprint_ratio,
        max_levels,
        intersection_density
    FROM brewgis.assessor.parcel_bft_classification
),

auth_res AS (
    SELECT apn, authoritative_residential_sqft, authoritative_non_residential_sqft
    FROM brewgis.assessor.authoritative_residential_area
)

SELECT
    c.apn,
    c.built_form_key,
    c.built_form_key_source,
    c.du_subtype,
    c.is_residential,
    c.landuse,
    c.lot_size_acres,
    c.zone,
    c.land_development_category,
    c.actual_living_sqft,
    c.actual_building_sqft,
    c.property_type,
    c.sales_lot_size_acres,
    c.units,
    c.residential_building_sqft,
    c.commercial_building_sqft,
    c.industrial_building_sqft,
    c.other_building_sqft,
    c.total_footprint_sqft,
    c.building_count,
    c.footprint_ratio,
    c.max_levels,
    c.intersection_density,
    GREATEST(0, COALESCE(
        ar.authoritative_residential_sqft,
        c.residential_building_sqft,
        c.lot_size_acres * 43560 * 0.15
    )) AS pop_dasym_weight,
    GREATEST(0, COALESCE(
        ar.authoritative_non_residential_sqft,
        NULLIF(c.commercial_building_sqft + c.industrial_building_sqft + c.other_building_sqft, 0),
        c.lot_size_acres * 43560 * 0.1
    )) * (1.0 + COALESCE(c.intersection_density, 0.0) / 200.0) AS emp_dasym_weight
FROM classification c
LEFT JOIN auth_res ar ON c.apn = ar.apn;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_parcel_dasymetric_weights_apn_@snapshot_hash
  ON @this_model USING btree (apn);
  CREATE INDEX IF NOT EXISTS idx_parcel_dasymetric_weights_int_dens_@snapshot_hash
  ON @this_model USING btree (intersection_density);
ANALYZE @this_model;
