MODEL (
  name brewgis.@{region}.buildings_combined,
  kind VIEW,
  description 'PostGIS VIEW over the buildings bridge that restores SRID metadata with ST_SetSRID: the spatially deduplicated union of Overture and VIDA (Google, Microsoft) building footprints.',
  column_descriptions (
    geometry = 'Building footprint re-tagged as SRID 3857 (Web Mercator, meters).',
    wgs84_geometry = 'Building footprint re-tagged as SRID 4326 (degrees, EPSG:4326).',
    local_geometry = 'Building footprint re-tagged as the region local_srid; the bridge projects it from wgs84_geometry in DuckDB.',
    height = 'Building height in metres; null for VIDA rows.',
    levels = 'Number of building levels; null for VIDA rows.',
    class = 'Source building class label; null for VIDA rows.',
    source = 'Origin dataset of the record: overture or vida.',
    bf_source = 'Building-footprint provider for VIDA rows (google or microsoft); null for Overture.',
    confidence = 'VIDA confidence score for the footprint; null for Overture rows.'
  ),
  columns (
    geometry GEOMETRY(GEOMETRY, 3857),
    wgs84_geometry GEOMETRY(GEOMETRY, 4326),
    local_geometry GEOMETRY(GEOMETRY, @local_srid()),
    height DOUBLE,
    levels INTEGER,
    class TEXT,
    source TEXT,
    bf_source TEXT,
    confidence DOUBLE
  ),
  blueprints @region_blueprints()
);

-- Combined building footprints — PostGIS VIEW wrapping the DuckDB bridge table
-- with real SRIDs.
--
-- The bridge (``brewgis.<region>.buildings_combined_raw``) materializes the
-- Overture/VIDA dedup union through DuckDB, and that transfer writes SRID-less
-- WKB: every geometry in the bridge lands as SRID 0 however the SELECT tagged it
-- (see the bridge's header). Anything that reads the CRS — a tile server
-- transforming a source per tile, ``ST_Transform``, a ``create_layer``
-- registration — then fails on the bridge's own column.
--
-- This VIEW restores all three CRSs with ``ST_SetSRID``, the same repair
-- ``census/tiger_blocks.sql`` makes for its bridge.
--
-- ``buildings_combined_pg`` materializes the GiST-indexed PostGIS copy that
-- ``parcel_building_footprints`` joins against; the bridge itself cannot be
-- indexed from DuckDB.

SELECT
    ST_SetSRID(geometry, 3857) AS geometry,
    ST_SetSRID(wgs84_geometry, 4326) AS wgs84_geometry,
    ST_SetSRID(local_geometry, @local_srid()) AS local_geometry,
    height,
    levels,
    class,
    source,
    bf_source,
    confidence
FROM brewgis.@{region}.buildings_combined_raw;
