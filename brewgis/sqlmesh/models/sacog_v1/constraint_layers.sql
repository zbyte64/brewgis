MODEL (
  name brewgis.sacog_v1.constraint_layers,
  kind FULL,
  description 'Environmental constraint polygons the SACOG v1 database snapshot shipped with (streams, wetlands and vernal pools), subdivided, with the share of each overlap that comes off developable acreage.',
  column_descriptions (
    layer = 'Constraint layer the polygon comes from: streams, wetlands or vernal_pools.',
    discount_pct = 'Share of the overlapping parcel area excluded from developable acreage (percent, 0-100).',
    geom = 'Constraint polygon piece (ST_Subdivide, at most 256 vertices) at SRID 4326.',
    local_geom = 'The same piece in the project local_srid, made valid there (projection can fold a sliver into a self-intersection); env_constraint measures overlaps on it.'
  ),
  columns (
    layer TEXT,
    discount_pct DOUBLE PRECISION,
    geom GEOMETRY(POLYGON, 4326),
    local_geom GEOMETRY
  )
);

-- SACOG v1 snapshot constraint layers — what env_constraint discounts for the
-- workspace on the imported v1 base canvas (``sacog_v1.base_canvas``; see
-- constraints/constraint_layers.sql for how an analysis region's model is
-- picked). The snapshot is analyzed against its own data: these are the three
-- layers UrbanFootprint's environmental constraint module reads for SACOG,
-- restored in ``public`` from the v1 database dump, each taking the whole
-- overlap (100 %), so the snapshot's constrained acreage stays comparable with
-- UrbanFootprint's export. The SACOG reconstruction reads public FEMA/NWI
-- layers instead (``brewgis.sacog.constraint_layers``).
--
-- The dump stores CA Albers (EPSG:3310) coordinates with no SRID recorded, so
-- each geometry is tagged 3310 before it is brought into EPSG:4326 — the CRS
-- every base canvas stores parcels in, which env_constraint's index probe
-- needs. The polygons are subdivided for the same reason as the public layers.

WITH src AS (
    SELECT 'streams'::text AS layer, 100.0::double precision AS discount_pct, wkb_geometry AS geom
    FROM public.sac_cnty_streams
    UNION ALL
    SELECT 'wetlands'::text AS layer, 100.0::double precision AS discount_pct, wkb_geometry AS geom
    FROM public.sac_cnty_wetlands
    UNION ALL
    SELECT 'vernal_pools'::text AS layer, 100.0::double precision AS discount_pct, wkb_geometry AS geom
    FROM public.sac_cnty_vernal_pools
),

pieces AS (
    SELECT
        layer,
        discount_pct,
        ST_Subdivide(
            ST_CollectionExtract(ST_MakeValid(ST_Transform(ST_SetSRID(geom, 3310), 4326)), 3),
            256
        ) AS geom
    FROM src
    WHERE geom IS NOT NULL
)

SELECT
    layer,
    discount_pct,
    geom,
    -- Valid in 4326 is not valid in local_srid (see
    -- constraints/constraint_layers.sql): made valid there once.
    ST_CollectionExtract(ST_MakeValid(ST_Transform(geom, @local_srid())), 3) AS local_geom
FROM pieces;

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_sacog_v1_constraint_layers_geom_')
  ON @this_model USING GIST (geom);
ANALYZE @this_model;
