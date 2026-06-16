MODEL (
  name brewgis.assessor.parcel_building_sqft_by_type,
  kind INCREMENTAL_BY_UNIQUE_KEY (
    unique_key (apn),
    batch_size 100000
  ),
  audits (
    not_null(columns := (apn))
  ),
  dialect postgres,
  depends_on (
    brewgis.assessor.sacog_assessor_parcels,
    brewgis.staging.buildings_combined
  )
);

-- Parcel Building Square Footage by Type — per-parcel total building sqft
-- broken into 4 Overture-derived buckets: residential, commercial, industrial,
-- other.
--
-- Builds on parcel_building_footprints (which has total_footprint_sqft,
-- building_count, footprint_ratio, etc.) by re-joining buildings_combined
-- via the parcel geometry to classify each building's floor area.
--
-- Mixed-use buildings (class IS NULL or 'mixed') are split:
--   levels > 1  → ground floor = commercial, upper floors = residential
--   levels <= 1 → 50/50 residential / commercial

WITH parcels AS (
    SELECT
        apn,
        geometry,
        lot_size_acres
    FROM brewgis.assessor.sacog_assessor_parcels
),

-- Per-building sqft with class, then aggregate to parcel by class bucket.
-- Mixed-use split is computed at the row level before SUM.
overture_class_aggregation AS (
    SELECT
        apn,
        SUM(
            CASE
                WHEN class IS NULL OR class = 'mixed' THEN
                    CASE
                        WHEN COALESCE(NULLIF(levels, 0), 1) > 1
                        THEN building_sqft / COALESCE(NULLIF(levels, 0), 1)
                        ELSE building_sqft * 0.5
                    END
                WHEN class = 'commercial' THEN building_sqft
                ELSE 0
            END
        ) AS commercial_building_sqft,
        SUM(
            CASE
                WHEN class IS NULL OR class = 'mixed' THEN
                    CASE
                        WHEN COALESCE(NULLIF(levels, 0), 1) > 1
                        THEN building_sqft - (building_sqft / COALESCE(NULLIF(levels, 0), 1))
                        ELSE building_sqft * 0.5
                    END
                WHEN class = 'residential' THEN building_sqft
                ELSE 0
            END
        ) AS residential_building_sqft,
        SUM(
            CASE
                WHEN class = 'industrial' THEN building_sqft
                ELSE 0
            END
        ) AS industrial_building_sqft,
        SUM(
            CASE
                WHEN class IS NOT NULL
                     AND class NOT IN ('residential', 'commercial', 'industrial', 'mixed')
                THEN building_sqft
                ELSE 0
            END
        ) AS other_building_sqft
    FROM (
        SELECT
            sap.apn,
            bc.class,
            bc.levels,
            ST_Area(ST_Transform(ST_SetSRID(bc.geometry, 4326), @VAR('local_srid', 3310))) * 10.7639
                * COALESCE(NULLIF(bc.levels, 0), 1) AS building_sqft
        FROM parcels sap
        JOIN brewgis.staging.buildings_combined bc
            ON ST_Intersects(sap.geometry, ST_SetSRID(bc.geometry, 4326))
    ) detail
    GROUP BY apn
)

SELECT
    pbf.apn,
    pbf.total_footprint_sqft,
    pbf.building_count,
    pbf.footprint_ratio,
    pbf.lot_size_acres,
    COALESCE(oca.residential_building_sqft, 0)::double precision AS residential_building_sqft,
    COALESCE(oca.commercial_building_sqft, 0)::double precision AS commercial_building_sqft,
    COALESCE(oca.industrial_building_sqft, 0)::double precision AS industrial_building_sqft,
    COALESCE(oca.other_building_sqft, 0)::double precision AS other_building_sqft,
    pbf.residential_building_count,
    pbf.non_residential_building_count,
    pbf.max_levels,
    pbf.land_development_category,
    pbf.geometry
FROM brewgis.assessor.parcel_building_footprints pbf
LEFT JOIN overture_class_aggregation oca
    ON pbf.apn = oca.apn;

-- post_statements
@IF(@runtime_stage = 'evaluating',
  CREATE INDEX IF NOT EXISTS idx_parcel_building_sqft_by_type_geometry
  ON brewgis.assessor.parcel_building_sqft_by_type USING GIST (geometry)
);
ANALYZE brewgis.assessor.parcel_building_sqft_by_type;
