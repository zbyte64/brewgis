MODEL (
  name brewgis.assessor.parcel_building_footprints,
  kind INCREMENTAL_BY_UNIQUE_KEY (
    unique_key (apn),
    batch_size 100000
  ),
  audits (
    not_null(columns := (apn)),
    unique_values(columns := (apn,)),
    assert_overture_class_residential,
    assert_overture_class_commercial,
    assert_overture_class_industrial,
    assert_overture_mixed_use_split
  )
);

-- Parcel Building Footprints — per-parcel building footprint features extracted
-- from combined (Overture + VIDA) building footprints via spatial join to
-- assessor parcels.
--
-- Computes per-APN:
--   - total_footprint_sqft: sum of building floor areas (sqft × levels)
--   - building_count: total number of buildings (Overture + deduped VIDA)
--   - google_building_count: count of VIDA Google buildings
--   - microsoft_building_count: count of VIDA Microsoft buildings
--   - max_height: maximum building height in meters
--   - max_levels: maximum number of floors
--   - mean_confidence: mean VIDA confidence score (Google buildings)
--   - footprint_ratio: footprint area / parcel lot area (0-1)
--   - land_development_category: from assessor_use_codes via landuse prefix
--   - overture_*_sqft: per-class floor-area buckets using Overture class system
--     (replaces the need for a separate spatial join in parcel_building_sqft_by_type)

WITH building_stats AS (
    SELECT
        sap.apn,
        SUM(bwa.footprint_sqft * COALESCE(NULLIF(bwa.levels, 0), 1) * bwa.overlap_ratio) AS total_footprint_sqft,
        COUNT(*) AS building_count,
        MAX(bwa.height) AS max_height,
        MAX(bwa.levels) AS max_levels,
        COUNT(*) FILTER (WHERE bwa.bf_source = 'google') AS google_building_count,
        COUNT(*) FILTER (WHERE bwa.bf_source = 'microsoft') AS microsoft_building_count,
        AVG(bwa.confidence) AS mean_confidence,
        SUM(bwa.footprint_sqft * bwa.overlap_ratio)
            FILTER (WHERE bwa.class_category = 'residential') AS residential_building_sqft,
        SUM(bwa.footprint_sqft * bwa.overlap_ratio)
            FILTER (WHERE bwa.class_category != 'residential') AS non_residential_building_sqft,
        COUNT(*) FILTER (WHERE bwa.class_category = 'residential') AS residential_building_count,
        COUNT(*) FILTER (WHERE bwa.class_category != 'residential') AS non_residential_building_count,
        COUNT(DISTINCT bwa.class_category) AS distinct_class_categories,
        -- Overture class-based sqft buckets for parcel_building_sqft_by_type.
        -- Mixed-use (class_category = 'mixed'): ground floor = commercial,
        -- upper floors = residential. With 1 floor (or unknown), split 50/50.
        -- For levels > 1: bldg_sqft = footprint_sqft * levels,
        --   commercial = bldg_sqft / levels = footprint_sqft,
        --   residential = bldg_sqft - commercial = footprint_sqft * (levels - 1).
        SUM(
            CASE
                WHEN bwa.class_category = 'mixed' THEN
                    CASE
                        WHEN COALESCE(NULLIF(bwa.levels, 0), 1) > 1
                        THEN bwa.footprint_sqft
                        ELSE bwa.footprint_sqft * 0.5
                    END
                WHEN bwa.class_category = 'commercial' THEN bwa.footprint_sqft * COALESCE(NULLIF(bwa.levels, 0), 1)
                ELSE 0
            END * bwa.overlap_ratio
        )::double precision AS overture_commercial_sqft,
        SUM(
            CASE
                WHEN bwa.class_category = 'mixed' THEN
                    CASE
                        WHEN COALESCE(NULLIF(bwa.levels, 0), 1) > 1
                        THEN bwa.footprint_sqft * (COALESCE(NULLIF(bwa.levels, 0), 1) - 1)
                        ELSE bwa.footprint_sqft * 0.5
                    END
                WHEN bwa.class_category = 'residential' THEN bwa.footprint_sqft * COALESCE(NULLIF(bwa.levels, 0), 1)
                ELSE 0
            END * bwa.overlap_ratio
        )::double precision AS overture_residential_sqft,
        SUM(
            CASE WHEN bwa.class_category = 'industrial' THEN bwa.footprint_sqft * COALESCE(NULLIF(bwa.levels, 0), 1) ELSE 0 END * bwa.overlap_ratio
        )::double precision AS overture_industrial_sqft,
        SUM(
            CASE
                WHEN bwa.class_category = 'other'
                THEN bwa.footprint_sqft * COALESCE(NULLIF(bwa.levels, 0), 1)
                ELSE 0
            END * bwa.overlap_ratio
        )::double precision AS overture_other_sqft
    FROM brewgis.assessor.sacog_assessor_parcels sap
    CROSS JOIN LATERAL (
        SELECT
            b.*,
            CASE
                WHEN ST_CoveredBy(b.local_geometry, sap.local_geometry)
                    THEN 1.0
                ELSE ST_Area(ST_Intersection(sap.local_geometry, b.local_geometry))
                     / NULLIF(ST_Area(b.local_geometry), 0)
            END AS overlap_ratio
        FROM brewgis.staging.buildings_combined_pg b
        WHERE sap.local_geometry && b.local_geometry
          AND ST_Intersects(sap.local_geometry, b.local_geometry)
    ) bwa
    GROUP BY sap.apn
)

SELECT
    sap.apn,
    sap.geometry,
    sap.lot_size_acres,
    COALESCE(bs.total_footprint_sqft, 0) AS total_footprint_sqft,
    COALESCE(bs.building_count, 0) AS building_count,
    bs.max_height,
    bs.max_levels,
    COALESCE(bs.google_building_count, 0) AS google_building_count,
    COALESCE(bs.microsoft_building_count, 0) AS microsoft_building_count,
    bs.mean_confidence,
    COALESCE(bs.residential_building_sqft, 0) AS residential_building_sqft,
    COALESCE(bs.non_residential_building_sqft, 0) AS non_residential_building_sqft,
    COALESCE(bs.residential_building_count, 0) AS residential_building_count,
    COALESCE(bs.non_residential_building_count, 0) AS non_residential_building_count,
    COALESCE(bs.distinct_class_categories, 0) AS distinct_class_categories,
    COALESCE(bs.overture_commercial_sqft, 0)::double precision AS overture_commercial_sqft,
    COALESCE(bs.overture_residential_sqft, 0)::double precision AS overture_residential_sqft,
    COALESCE(bs.overture_industrial_sqft, 0)::double precision AS overture_industrial_sqft,
    COALESCE(bs.overture_other_sqft, 0)::double precision AS overture_other_sqft,
    CASE
        WHEN sap.lot_size_acres > 0
        THEN COALESCE(bs.total_footprint_sqft, 0)
             / NULLIF(sap.lot_size_acres * 43560, 0)
        ELSE 0
    END AS footprint_ratio,
    sap.land_development_category
FROM brewgis.assessor.sacog_assessor_parcels sap
LEFT JOIN building_stats bs ON sap.apn = bs.apn;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_parcel_building_footprints_geometry
  ON @this_model USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS idx_parcel_building_footprints_apn
  ON @this_model USING btree (apn);
ANALYZE @this_model;
