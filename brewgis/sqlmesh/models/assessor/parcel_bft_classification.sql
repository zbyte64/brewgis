MODEL (
  name brewgis.assessor.parcel_bft_classification,
  kind VIEW
);

-- Parcel Built Form Classification — thin output VIEW.
--
-- Reads from the decomposed tier resolver (parcel_bft_resolved) and LEFT JOINs
-- assessor/sales/building metrics for the full output schema.
--
-- Decomposed from a single 359-line INCREMENTAL into 7 tier models:
--   tier1_sales (VIEW)   → highest priority: property type / sales data
--   tier0_landuse (VIEW)  → landuse code classification
--   tier2_footprints (VIEW) → building footprint classification
--   tier3_knn (INCREMENTAL) → KNN spatial imputation
--   tier3b_agricultural (VIEW) → large-lot agricultural
--   tier4_catchall (VIEW) → catch-all heuristic
--   parcel_bft_resolved (VIEW) → COALESCE priority chain + du_subtype derivation

WITH resolved AS (
    SELECT * FROM brewgis.assessor.parcel_bft_resolved
)
SELECT
    r.apn, r.built_form_key, r.built_form_key_source,
    r.du_subtype, r.is_residential,
    ap.landuse, ap.lot_size_acres, ap.zone,
    COALESCE(ap.land_development_category, 'urban') AS land_development_category,
    COALESCE(sd.actual_living_sqft, 0)::double precision AS actual_living_sqft,
    COALESCE(sd.actual_building_sqft, 0)::double precision AS actual_building_sqft,
    sd.property_type, sd.sales_lot_size_acres, sd.units,
    COALESCE(bs.residential_building_sqft, 0)::double precision AS residential_building_sqft,
    COALESCE(bs.commercial_building_sqft, 0)::double precision AS commercial_building_sqft,
    COALESCE(bs.industrial_building_sqft, 0)::double precision AS industrial_building_sqft,
    COALESCE(bs.other_building_sqft, 0)::double precision AS other_building_sqft,
    COALESCE(bs.total_footprint_sqft, 0)::double precision AS total_footprint_sqft,
    COALESCE(bs.building_count, 0)::integer AS building_count,
    COALESCE(bs.footprint_ratio, 0)::double precision AS footprint_ratio,
    COALESCE(bs.max_levels, 0)::integer AS max_levels,
    COALESCE(id.intersection_density, 0)::double precision AS intersection_density
FROM resolved r
JOIN brewgis.assessor.sacog_assessor_parcels ap ON r.apn = ap.apn
LEFT JOIN brewgis.assessor.sacog_assessor_sales_deduped sd ON r.apn = sd.apn
LEFT JOIN brewgis.assessor.parcel_building_sqft_by_type bs ON r.apn = bs.apn
LEFT JOIN brewgis.assessor.overture_intersection_density id ON r.apn = id.apn;
