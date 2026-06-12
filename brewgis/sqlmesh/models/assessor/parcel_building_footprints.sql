MODEL (
  name brewgis.assessor.parcel_building_footprints,
  kind INCREMENTAL_BY_UNIQUE_KEY (
    unique_key (apn),
    batch_size 100000
  ),
  audits (
    not_null(columns := (apn))
  )
);

-- Parcel Building Footprints — per-parcel building footprint features extracted
-- from combined (Overture + VIDA) building footprints via spatial join to
-- assessor parcels.
--
-- Computes per-APN:
--   - total_footprint_sqft: sum of building footprint areas (m² → sqft)
--   - building_count: total number of buildings (Overture + deduped VIDA)
--   - google_building_count: count of VIDA Google buildings
--   - microsoft_building_count: count of VIDA Microsoft buildings
--   - max_height: maximum building height in meters
--   - max_levels: maximum number of floors
--   - mean_confidence: mean VIDA confidence score (Google buildings)
--   - footprint_ratio: footprint area / parcel lot area (0-1)
--   - land_development_category: from assessor_use_codes via landuse prefix

WITH building_stats AS (
    SELECT
        sap.apn,
        SUM(ST_Area(ST_Transform(ST_SetSRID(bc.geometry, 4326), @VAR('local_srid', 3310))) * 10.7639 * COALESCE(NULLIF(bc.levels, 0), 1)) AS total_footprint_sqft,
        COUNT(*) AS building_count,
        MAX(bc.height) AS max_height,
        MAX(bc.levels) AS max_levels,
        COUNT(*) FILTER (WHERE bc.bf_source = 'google') AS google_building_count,
        COUNT(*) FILTER (WHERE bc.bf_source = 'microsoft') AS microsoft_building_count,
        AVG(bc.confidence) AS mean_confidence,
        SUM(ST_Area(ST_Transform(ST_SetSRID(bc.geometry, 4326), @VAR('local_srid', 3310))) * 10.7639)
            FILTER (WHERE bc.class IN ('residential','house','apartments','dormitory','detached','semidetached','terrace','bungalow')) AS residential_building_sqft,
        SUM(ST_Area(ST_Transform(ST_SetSRID(bc.geometry, 4326), @VAR('local_srid', 3310))) * 10.7639)
            FILTER (WHERE bc.class NOT IN ('residential','house','apartments','dormitory','detached','semidetached','terrace','bungalow') OR bc.class IS NULL) AS non_residential_building_sqft,
        COUNT(*) FILTER (WHERE bc.class IN ('residential','house','apartments','dormitory','detached','semidetached','terrace','bungalow')) AS residential_building_count,
        COUNT(*) FILTER (WHERE bc.class NOT IN ('residential','house','apartments','dormitory','detached','semidetached','terrace','bungalow') OR bc.class IS NULL) AS non_residential_building_count
    FROM brewgis.assessor.sacog_assessor_parcels sap
    JOIN brewgis.staging.buildings_combined bc
        ON ST_Intersects(sap.geometry, ST_SetSRID(bc.geometry, 4326))
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
    CASE
        WHEN sap.lot_size_acres > 0
        THEN COALESCE(bs.total_footprint_sqft, 0)
             / NULLIF(sap.lot_size_acres * 43560, 0)
        ELSE 0
    END AS footprint_ratio,
    COALESCE(auc.category, 'urban') AS land_development_category
FROM brewgis.assessor.sacog_assessor_parcels sap
LEFT JOIN building_stats bs ON sap.apn = bs.apn
LEFT JOIN brewgis.seeds.assessor_use_codes auc
    ON LEFT(COALESCE(sap.landuse::text, ''), 2) = auc.use_code::text;

-- post_statements
-- (buildings_combined is DuckDB gateway, so index must live here)
@IF(@runtime_stage = 'evaluating',
  CREATE INDEX IF NOT EXISTS idx_buildings_combined_geometry
  ON brewgis.staging.buildings_combined USING GIST (geometry)
);
ANALYZE brewgis.staging.buildings_combined;

@IF(@runtime_stage = 'evaluating',
  CREATE INDEX IF NOT EXISTS idx_parcel_building_footprints_geometry
  ON brewgis.assessor.parcel_building_footprints USING GIST (geometry)
);
ANALYZE brewgis.assessor.parcel_building_footprints;
