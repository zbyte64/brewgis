MODEL (
  name brewgis.tests.test_stage_building_footprints,
  kind VIEW,
  audits (
    not_null(columns := (apn))
  )
);

-- Test staging model: produces output matching parcel_building_sqft_by_type schema
-- from the test_overture_buildings seed data, spatially joined to test assessor parcels.
--
-- Each building's sqft is computed as footprint × levels, classified by Overture class.
-- Mixed/unknown class buildings use the methodology split:
--   levels > 1 → ground floor commercial, upper floors residential
--   levels ≤ 1 → 50/50 residential/commercial split

WITH building_footprints AS (
    SELECT
        sap.apn,
        sap.geometry,
        sap.lotsize AS lot_size_acres,
        b.id,
        b.class,
        b.levels,
        ST_Area(b.geometry) * 10.7639 AS footprint_sqft
    FROM brewgis.seeds.test_assessor_parcels sap
    JOIN brewgis.seeds.test_overture_buildings b
        ON ST_Intersects(sap.geometry, b.geometry)
),

building_metrics AS (
    SELECT
        apn,
        SUM(footprint_sqft * COALESCE(NULLIF(levels, 0), 1)) AS total_footprint_sqft,
        COUNT(*) AS building_count,
        MAX(COALESCE(NULLIF(levels, 0), 1)) AS max_levels,
        SUM(footprint_sqft * COALESCE(NULLIF(levels, 0), 1)) / NULLIF(MIN(lot_size_acres) * 43560, 0) AS footprint_ratio,
        SUM(
            CASE
                WHEN class IS NULL OR class = 'mixed' THEN
                    CASE
                        WHEN COALESCE(NULLIF(levels, 0), 1) > 1 THEN footprint_sqft
                        ELSE footprint_sqft * 0.5
                    END
                WHEN class = 'commercial' THEN footprint_sqft * COALESCE(NULLIF(levels, 0), 1)
                ELSE 0
            END
        )::double precision AS commercial_building_sqft,
        SUM(
            CASE
                WHEN class IS NULL OR class = 'mixed' THEN
                    CASE
                        WHEN COALESCE(NULLIF(levels, 0), 1) > 1
                        THEN footprint_sqft * (COALESCE(NULLIF(levels, 0), 1) - 1)
                        ELSE footprint_sqft * 0.5
                    END
                WHEN class IN ('house', 'apartment', 'residential', 'semi', 'detached', 'terrace', 'bungalow', 'dwelling_house', 'cabin', 'ger', 'houseboat', 'stilt_house', 'static_caravan', 'trullo', 'dormitory', 'semidetached')
                    THEN footprint_sqft * COALESCE(NULLIF(levels, 0), 1)
                ELSE 0
            END
        )::double precision AS residential_building_sqft,
        SUM(
            CASE WHEN class = 'industrial' THEN footprint_sqft * COALESCE(NULLIF(levels, 0), 1) ELSE 0 END
        )::double precision AS industrial_building_sqft,
        SUM(
            CASE
                WHEN class IS NOT NULL
                     AND class NOT IN ('residential', 'commercial', 'industrial', 'mixed', 'house', 'apartment',
                          'semi', 'detached', 'terrace', 'bungalow', 'dwelling_house', 'cabin', 'ger',
                          'houseboat', 'stilt_house', 'static_caravan', 'trullo', 'dormitory', 'semidetached',
                          'agricultural', 'civic')
                THEN footprint_sqft * COALESCE(NULLIF(levels, 0), 1)
                ELSE 0
            END
        )::double precision AS other_building_sqft
    FROM building_footprints
    GROUP BY apn
)

SELECT
    sap.apn,
    COALESCE(bm.total_footprint_sqft, 0)::double precision AS total_footprint_sqft,
    COALESCE(bm.building_count, 0)::integer AS building_count,
    COALESCE(bm.footprint_ratio, 0)::double precision AS footprint_ratio,
    sap.lotsize::double precision AS lot_size_acres,
    COALESCE(bm.residential_building_sqft, 0)::double precision AS residential_building_sqft,
    COALESCE(bm.commercial_building_sqft, 0)::double precision AS commercial_building_sqft,
    COALESCE(bm.industrial_building_sqft, 0)::double precision AS industrial_building_sqft,
    COALESCE(bm.other_building_sqft, 0)::double precision AS other_building_sqft,
    COALESCE(bm.building_count, 0)::integer AS residential_building_count,
    0::integer AS non_residential_building_count,
    COALESCE(bm.max_levels, 0)::integer AS max_levels,
    'urban'::text AS land_development_category,
    sap.geometry
FROM brewgis.seeds.test_assessor_parcels sap
LEFT JOIN building_metrics bm ON sap.apn = bm.apn;
