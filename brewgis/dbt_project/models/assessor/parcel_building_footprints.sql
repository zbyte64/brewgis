{#
    Parcel Building Footprints — per-parcel building footprint features extracted
    from Overture Maps building footprints via spatial join to assessor parcels.

    Computes per-APN:
      - total_footprint_sqft: sum of building footprint areas (m² → sqft)
      - building_count: number of buildings intersecting the parcel
      - max_height: maximum building height in meters
      - max_levels: maximum number of floors
      - footprint_ratio: footprint area / parcel lot area (0-1)
      - land_development_category: from assessor_use_codes via landuse prefix

    No sales data is joined — this model is purely geometry + Overture data,
    avoiding circular dependencies with parcel_dasymetric_weights.

    Materialized as: table
        - Unique index on apn
        - GIST index on geometry
#}

{{ config(materialized='table',
    indexes=[
        {'columns': ['apn'], 'unique': True},
        {'columns': ['geometry'], 'type': 'gist'},
    ])
}}

WITH building_stats AS (
    SELECT
        sap.apn,
        SUM(ST_Area(ob.geometry) * 10.7639) AS total_footprint_sqft,
        COUNT(*) AS building_count,
        MAX(ob.height) AS max_height,
        MAX(ob.levels) AS max_levels
    FROM {{ ref('sacog_assessor_parcels') }} sap
    JOIN {{ source('brewgis', 'overture_buildings') }} ob
        ON ST_Intersects(sap.geometry, ob.geometry)
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
    CASE
        WHEN sap.lot_size_acres > 0
        THEN COALESCE(bs.total_footprint_sqft, 0)
             / NULLIF(sap.lot_size_acres * 43560, 0)
        ELSE 0
    END AS footprint_ratio,
    COALESCE(auc.category, 'urban') AS land_development_category
FROM {{ ref('sacog_assessor_parcels') }} sap
LEFT JOIN building_stats bs ON sap.apn = bs.apn
LEFT JOIN {{ ref('assessor_use_codes') }} auc
    ON LEFT(COALESCE(sap.landuse::text, ''), 2) = auc.use_code::text
