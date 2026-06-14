MODEL (
  name brewgis.assessor.parcel_dasymetric_weights,
  kind INCREMENTAL_BY_UNIQUE_KEY (
    unique_key (apn),
    batch_size 100000
  ),
  audits (
    not_null(columns := (apn))
  )
);

-- Dasymetric Weights — per-parcel population and employment weights.
--
-- Merges assessor parcel geometries with sales building data, estimates building
-- sqft for parcels without sales records using land-use-type medians, and computes
-- pop_dasym_weight and emp_dasym_weight per parcel.
--
-- Also computes du_subtype (assessor-based dwelling unit sub-type classification)
-- and du_dasym_weight (dasymetric weight for DU sub-type allocation).
--
-- Weight formulas:
--   pop_dasym_weight = pop_mult * COALESCE(
--       actual_living_sqft,
--       estimated_living_sqft,
--       footprint_imputed_living_sqft,
--       lotsize * impervious_fraction,
--       lotsize
--   )
--   emp_dasym_weight = emp_mult * COALESCE(
--       actual_building_sqft,
--       estimated_building_sqft,
--       footprint_imputed_building_sqft,
--       lotsize * impervious_fraction,
--       lotsize
--   ) * (1.0 + COALESCE(intersection_density, 0.0) / 200.0)

WITH assessor_parcels AS (
    SELECT
        apn,
        geometry,
        COALESCE(NULLIF(lot_size_acres, 0), 0.01) AS lot_size_acres,
        landuse
    FROM brewgis.assessor.sacog_assessor_parcels
),

sales_data AS (
    SELECT
        apn,
        actual_living_sqft,
        actual_building_sqft,
        property_type,
        lot_size_acres,
        units
    FROM (
        SELECT
            apn,
            living_area AS actual_living_sqft,
            building_sf AS actual_building_sqft,
            property_type,
            lot_size_acres,
            units,
            ROW_NUMBER() OVER (
                PARTITION BY apn
                ORDER BY
                    CASE
                        WHEN living_area IS NOT NULL AND building_sf IS NOT NULL THEN 0
                        WHEN living_area IS NOT NULL THEN 1
                        WHEN building_sf IS NOT NULL THEN 2
                        ELSE 3
                    END,
                    year_built DESC NULLS LAST
            ) AS rn
        FROM public.sacog_assessor_sales_raw
        WHERE living_area IS NOT NULL OR building_sf IS NOT NULL
    ) deduped_sales
    WHERE rn = 1
),

-- Per-property-type median building sizes from sales data
building_medians AS (
    SELECT
        property_type,
        parcel_count,
        median_living_area,
        median_building_sf,
        median_lot_size_acres
    FROM brewgis.assessor.assessor_building_medians
),

-- Best median values (most common property type) — materialized once, not per row
best_medians AS (
    SELECT * FROM building_medians ORDER BY parcel_count DESC LIMIT 1
),

estimated AS (
    SELECT
        ap.apn,
        ap.lot_size_acres,
        bm.median_living_area,
        bm.median_building_sf,
        bm.median_lot_size_acres,
        CASE
            WHEN bm.median_living_area IS NOT NULL AND bm.median_lot_size_acres > 0
            THEN bm.median_living_area * (ap.lot_size_acres / bm.median_lot_size_acres)
            WHEN bm.median_living_area IS NOT NULL
            THEN bm.median_living_area
            ELSE NULL
        END AS estimated_living_sqft,
        CASE
            WHEN bm.median_building_sf IS NOT NULL AND bm.median_lot_size_acres > 0
            THEN bm.median_building_sf * (ap.lot_size_acres / bm.median_lot_size_acres)
            WHEN bm.median_building_sf IS NOT NULL
            THEN bm.median_building_sf
            ELSE NULL
        END AS estimated_building_sqft
    FROM assessor_parcels ap
    CROSS JOIN best_medians bm
),

-- SACOG land-use code → category mapping.
--
-- SACOG parcel codes use a letter-prefix convention:
--   A* = Residential, B* = Commercial, C* = Civic           → urban
--   D* = Vacant, G* = Golf/Parks, W* = Water                → undeveloped
--   E* = Education, H* = Hotel/Lodging                      → urban
--   F* = Farming/Agriculture                                 → agricultural
--   I* = Industrial/Office                                   → industrial
--   M* = Misc/Public (MP=park, MR=road, MW=well + others)   → undeveloped exceptions, else urban
--
-- Also preserves the existing assessor_use_codes join for
-- jurisdictions with 2-digit numeric codes (10-90).
sacog_category AS (
    SELECT
        apn,
        CASE
            WHEN landuse IS NULL OR landuse = '' THEN 'undeveloped'
            WHEN LEFT(landuse, 1) = 'A' THEN 'urban'
            WHEN LEFT(landuse, 1) = 'B' THEN 'urban'
            WHEN LEFT(landuse, 1) = 'C' THEN 'urban'
            WHEN LEFT(landuse, 1) = 'D' THEN 'undeveloped'
            WHEN LEFT(landuse, 1) = 'E' THEN 'urban'
            WHEN LEFT(landuse, 1) = 'F' THEN 'agricultural'
            WHEN LEFT(landuse, 1) = 'G' THEN 'undeveloped'
            WHEN LEFT(landuse, 1) = 'H' THEN 'urban'
            WHEN LEFT(landuse, 1) = 'I' THEN 'industrial'
            -- M* two-letter exceptions: infrastructure → undeveloped
            WHEN LEFT(landuse, 2) IN ('MP', 'MR', 'MW', 'MD', 'MF', 'MG', 'ML') THEN 'undeveloped'
            WHEN LEFT(landuse, 1) = 'M' THEN 'urban'
            WHEN LEFT(landuse, 1) = 'W' THEN 'undeveloped'
            ELSE 'undeveloped'
        END AS land_development_category
    FROM assessor_parcels
),

classified AS (
    SELECT
        ap.apn,
        ap.lot_size_acres,
        COALESCE(auc.category, sc.land_development_category, 'urban') AS land_development_category
    FROM assessor_parcels ap
    LEFT JOIN brewgis.seeds.assessor_use_codes auc
        ON LEFT(COALESCE(ap.landuse::text, ''), 2) = auc.use_code::text
    LEFT JOIN sacog_category sc ON ap.apn = sc.apn
),

-- NLCD impervious surface fraction joined spatially via SACOG parcels
-- Picks best match per APN by bounding-box overlap area (avoids expensive
-- ST_Area(ST_Intersection(…)) on full polygon geometry)
nlcd_join AS (
    SELECT DISTINCT ON (ap.apn)
        ap.apn,
        COALESCE(nlcd.impervious_fraction, 0.0) AS impervious_fraction
    FROM assessor_parcels ap
    LEFT JOIN brewgis.comparison.sacog_parcel_shim sp
        ON ST_Intersects(ap.geometry, sp.geometry)
    LEFT JOIN brewgis.nlcd.nlcd_parcel_stats nlcd
        ON sp.parcel_id = nlcd.parcel_id
    ORDER BY ap.apn, COALESCE(ST_Area(ST_Intersection(ST_Envelope(ap.geometry), ST_Envelope(sp.geometry))), 0) DESC
),

-- OSM enabled defaults to false — intersection_density is NULL
osm_join AS (
    SELECT ap.apn, NULL::double precision AS intersection_density
    FROM assessor_parcels ap
),

-- Assemble final dasymetric weights
assembled AS (
    SELECT
        ap.apn,
        ap.geometry,
        ap.lot_size_acres,
        cl.land_development_category,
        sd.actual_living_sqft,
        sd.actual_building_sqft,
        est.estimated_living_sqft,
        est.estimated_building_sqft,
        fi.imputed_living_sqft AS footprint_imputed_living_sqft,
        fi.imputed_building_sqft AS footprint_imputed_building_sqft,
        fi.imputed_units AS footprint_imputed_units,
        fi.imputed_property_type AS footprint_imputed_property_type,
        fi.residential_building_sqft,
        fi.non_residential_building_sqft,
        fi.residential_building_count,
        fi.non_residential_building_count,
        fi.max_levels,
        nj.impervious_fraction,
        oj.intersection_density,
        sd.property_type,
        sd.lot_size_acres AS sales_lot_size_acres,
        sd.units
    FROM assessor_parcels ap
    LEFT JOIN classified cl ON ap.apn = cl.apn
    LEFT JOIN sales_data sd ON ap.apn = sd.apn
    LEFT JOIN estimated est ON ap.apn = est.apn
    LEFT JOIN brewgis.assessor.parcel_footprint_imputed fi ON ap.apn = fi.apn
    LEFT JOIN nlcd_join nj ON ap.apn = nj.apn
    LEFT JOIN osm_join oj ON ap.apn = oj.apn
),

-- DU sub-type classification from assessor sales data
du_classification AS (
    SELECT
        apn,
        CASE
            WHEN (property_type IN ('SFR', 'Single Family Residence') OR property_type LIKE 'Single Family%')
                AND COALESCE(sales_lot_size_acres, lot_size_acres) < 0.15 THEN 'detsf_sl'
            WHEN (property_type IN ('SFR', 'Single Family Residence') OR property_type LIKE 'Single Family%')
                AND COALESCE(sales_lot_size_acres, lot_size_acres) >= 0.15 THEN 'detsf_ll'
            WHEN property_type IN ('Condo', 'Condominium') THEN 'attsf'
            WHEN (property_type IN ('MF', 'Multiple Family Residence') OR property_type LIKE 'Multiple Family%')
                AND COALESCE(units, 0) BETWEEN 2 AND 4 THEN 'mf2to4'
            WHEN (property_type IN ('MF', 'Multiple Family Residence') OR property_type LIKE 'Multiple Family%')
                AND COALESCE(units, 0) >= 5 THEN 'mf5p'
            WHEN footprint_imputed_property_type IN ('Single Family Residence')
                AND COALESCE(sales_lot_size_acres, lot_size_acres) < 0.15 THEN 'detsf_sl'
            WHEN footprint_imputed_property_type IN ('Single Family Residence')
                AND COALESCE(sales_lot_size_acres, lot_size_acres) >= 0.15 THEN 'detsf_ll'
            WHEN footprint_imputed_property_type IN ('Condominium') THEN 'attsf'
            WHEN footprint_imputed_property_type IN ('Multiple Family Residence')
                AND COALESCE(footprint_imputed_units, 0) BETWEEN 2 AND 4 THEN 'mf2to4'
            WHEN footprint_imputed_property_type IN ('Multiple Family Residence')
                AND COALESCE(footprint_imputed_units, 0) >= 5 THEN 'mf5p'
            ELSE NULL
        END AS du_subtype,
        COALESCE(
            NULLIF(units, 0),
            NULLIF(footprint_imputed_units, 0),
            1
        )::double precision AS du_dasym_weight
    FROM assembled
)

SELECT
    a.apn,
    a.geometry,
    a.lot_size_acres,
    a.land_development_category,
    a.actual_living_sqft,
    a.actual_building_sqft,
    a.estimated_living_sqft,
    a.estimated_building_sqft,
    a.footprint_imputed_living_sqft,
    a.footprint_imputed_building_sqft,
    a.impervious_fraction,
    a.intersection_density,
    a.residential_building_sqft,
    a.non_residential_building_sqft,
    a.residential_building_count,
    a.non_residential_building_count,
    a.max_levels,
    -- Population weight
    COALESCE(
        a.actual_living_sqft,
        a.footprint_imputed_living_sqft,
        -- Tier 2.5: direct building footprint area × levels for residential buildings
        CASE WHEN a.residential_building_sqft > 0
             THEN a.residential_building_sqft * COALESCE(a.max_levels, 1) END,
        a.estimated_living_sqft,
        a.lot_size_acres * COALESCE(a.impervious_fraction, 1.0),
        a.lot_size_acres
    ) AS pop_dasym_weight,
    -- Employment weight with OSM boost
    COALESCE(
        a.actual_building_sqft,
        a.footprint_imputed_building_sqft,
        -- Tier 2.5: direct building footprint area × levels for non-residential buildings
        CASE WHEN a.non_residential_building_sqft > 0
             THEN a.non_residential_building_sqft * COALESCE(a.max_levels, 1) END,
        a.estimated_building_sqft,
        a.lot_size_acres * COALESCE(a.impervious_fraction, 1.0),
        a.lot_size_acres
    ) * (1.0 + COALESCE(a.intersection_density, 0.0) / 200.0) AS emp_dasym_weight,
    -- DU sub-type and weight from assessor data
    dc.du_subtype,
    dc.du_dasym_weight
FROM assembled a
LEFT JOIN du_classification dc ON a.apn = dc.apn;

-- post_statements
@IF(@runtime_stage = 'evaluating',
  CREATE INDEX IF NOT EXISTS idx_parcel_dasymetric_weights_geometry
  ON brewgis.assessor.parcel_dasymetric_weights USING GIST (geometry)
);
ANALYZE brewgis.assessor.parcel_dasymetric_weights;
