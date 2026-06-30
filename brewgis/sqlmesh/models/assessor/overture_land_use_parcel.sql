MODEL (
  name brewgis.assessor.overture_land_use_parcel,
  kind INCREMENTAL_BY_UNIQUE_KEY (
    unique_key (parcel_id),
    batch_size 100000
  ),
  audits (
    not_null(columns := (parcel_id)),
    unique_values(columns := (parcel_id,))
  )
);

-- pre_statements
  CREATE INDEX IF NOT EXISTS idx_overture_land_use_bridge_geometry
  ON brewgis.staging.overture_land_use USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS idx_overture_land_use_area
  ON brewgis.staging.overture_land_use USING BTREE (ST_Area(geometry));

-- Overture Land Use per Parcel — spatial join of Overture land use polygons
-- to base canvas parcels.
--
-- Strategy (in priority order):
--   1. Centroid test: if the parcel's centroid falls inside an Overture land
--      use polygon, that polygon's classification wins (smallest polygon
--      wins ties for most specific classification).
--   2. Area-weighted voting: if centroid test fails (e.g. parcel straddles
--      multiple land uses), pick the Overture polygon with the largest
--      total area that intersects the parcel (heuristic: largest polygon
--      generally represents the dominant land use).
--   3. Maps Overture subtype+class → land_development_category via the
--      overture_land_use_map seed table.
--
-- NOTE: Parcels that overlap no Overture land use polygon are silently
-- omitted from the output. These parcels will have NULL overture_category
-- downstream and fall through to the 'urban' default.

WITH

-- Priority 1: centroid-inside-polygon join
-- References base_canvas_geometry directly (not via CTE) so the GIST
-- expression index on ST_Centroid(geometry) is visible to the planner.
-- The overture data uses a subquery (not CTE) for ST_SetSRID — necessary
-- because overture.geometry has SRID 0 and ST_Contains requires matching
-- SRIDs. The planner inverts the join: seq-scan overture + index-look-up
-- parcels, completing in ~1s.
centroid_match AS (
    SELECT DISTINCT ON (bg.parcel_id)
        bg.parcel_id,
        olu.subtype AS overture_land_use_subtype,
        olu.class AS overture_land_use_class
    FROM brewgis.base_canvas.base_canvas_geometry bg
    JOIN (
        SELECT ST_SetSRID(geometry, @VAR('default_srid', 4326)) AS geometry,
               subtype, class
        FROM brewgis.staging.overture_land_use
    ) olu
        ON ST_Centroid(bg.geometry) && ST_Envelope(olu.geometry)
        AND ST_Contains(olu.geometry, ST_Centroid(bg.geometry))
    ORDER BY bg.parcel_id, ST_Area(olu.geometry) ASC
),

-- Parcels that did NOT match via centroid test
-- References base_canvas_geometry directly for the same reason.
unmatched AS (
    SELECT bg.parcel_id, bg.geometry
    FROM brewgis.base_canvas.base_canvas_geometry bg
    LEFT JOIN centroid_match cm ON bg.parcel_id = cm.parcel_id
    WHERE cm.parcel_id IS NULL
),

-- Priority 2: LATERAL index-lookup for unmatched parcels
-- For each unmatched parcel, index-scans overture_land_use via GIST
-- on raw geometry (bypasses ST_SetSRID wrapper so index is usable).
-- Casts parcel geometry to SRID 0 to match overture's unset SRID.
area_vote AS (
    SELECT
        u.parcel_id,
        olu.subtype AS overture_land_use_subtype,
        olu.class AS overture_land_use_class
    FROM unmatched u
    CROSS JOIN LATERAL (
        SELECT olu2.subtype, olu2.class
        FROM brewgis.staging.overture_land_use olu2
        WHERE ST_Intersects(olu2.geometry, ST_SetSRID(u.geometry, 0))
        ORDER BY ST_Area(olu2.geometry) DESC
        LIMIT 1
    ) olu
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
  CREATE INDEX IF NOT EXISTS idx_overture_land_use_parcel_parcel_id_@snapshot_hash
  ON @this_model USING btree (parcel_id);
