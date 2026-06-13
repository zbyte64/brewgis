MODEL (
  name brewgis.assessor.overture_land_use_parcel,
  kind INCREMENTAL_BY_UNIQUE_KEY (
    unique_key (parcel_id),
    batch_size 100000
  ),
  audits (
    not_null(columns := (parcel_id))
  )
);

-- Overture Land Use per Parcel — spatial join of Overture land use polygons
-- to base canvas parcels.
--
-- Strategy (in priority order):
--   1. Centroid test: if the parcel's centroid falls inside an Overture land
--      use polygon, that polygon's classification wins.
--   2. Area-weighted voting: if centroid test fails (e.g. parcel straddles
--      multiple land uses), find the Overture polygon with the largest
--      intersection area.
--   3. Maps Overture subtype+class → land_development_category via the
--      overture_land_use_map seed table.

WITH parcels AS (
    SELECT parcel_id, geometry
    FROM brewgis.base_canvas.base_canvas_geometry
),

overture_lu AS (
    SELECT
        ST_SetSRID(geometry, @VAR('default_srid', 4326)) AS geometry,
        subtype,
        class
    FROM brewgis.staging.overture_land_use
),

-- Priority 1: centroid-inside-polygon join
centroid_match AS (
    SELECT DISTINCT ON (p.parcel_id)
        p.parcel_id,
        olu.subtype AS overture_land_use_subtype,
        olu.class AS overture_land_use_class
    FROM parcels p
    JOIN overture_lu olu
        ON ST_Centroid(p.geometry) && ST_Envelope(olu.geometry)
        AND ST_Contains(olu.geometry, ST_Centroid(p.geometry))
),

-- Parcels that did NOT match via centroid test
unmatched AS (
    SELECT p.parcel_id, p.geometry
    FROM parcels p
    LEFT JOIN centroid_match cm ON p.parcel_id = cm.parcel_id
    WHERE cm.parcel_id IS NULL
),

-- Priority 2: area-weighted voting for unmatched parcels
area_vote AS (
    SELECT DISTINCT ON (u.parcel_id)
        u.parcel_id,
        olu.subtype AS overture_land_use_subtype,
        olu.class AS overture_land_use_class
    FROM unmatched u
    JOIN overture_lu olu
        ON ST_Intersects(olu.geometry, u.geometry)
    ORDER BY u.parcel_id,
        ST_Area(ST_Intersection(olu.geometry, u.geometry)) DESC
),

combined AS (
    SELECT
        parcel_id,
        overture_land_use_subtype,
        overture_land_use_class
    FROM centroid_match

    UNION ALL

    SELECT
        parcel_id,
        overture_land_use_subtype,
        overture_land_use_class
    FROM area_vote
)

SELECT
    c.parcel_id,
    c.overture_land_use_subtype,
    c.overture_land_use_class,
    COALESCE(
        oym_class.category,
        oym_subtype.category,
        'urban'::text
    ) AS overture_category
FROM combined c
LEFT JOIN brewgis.seeds.overture_land_use_map oym_class
    ON c.overture_land_use_subtype = oym_class.subtype
    AND c.overture_land_use_class = oym_class.class
LEFT JOIN brewgis.seeds.overture_land_use_map oym_subtype
    ON c.overture_land_use_subtype = oym_subtype.subtype
    AND oym_subtype.class IS NULL;

-- post_statements
@IF(@runtime_stage = 'evaluating',
  CREATE INDEX IF NOT EXISTS idx_overture_land_use_parcel_parcel_id
  ON brewgis.assessor.overture_land_use_parcel (parcel_id)
);
