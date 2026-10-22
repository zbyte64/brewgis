MODEL (
  name brewgis.@{workspace_schema}.trip_zones_package_raw,
  kind FULL,
  description 'Reference trip-length zones shipped in the workspace package (e.g. SACSIM travel-model zones), materialized in PostGIS by DuckDB, one zone per row with its round-trip lengths by trip purpose.',
  column_descriptions (
    geometry = 'Zone polygon in EPSG:4326 stored as SRID 0: the DuckDB-to-PostGIS transfer writes SRID-less WKB. Read the workspace''s trip_length_zones model for the re-tagged column.',
    productions_hbw = 'Mean round-trip length of home-based work trips produced in the zone (miles).',
    productions_hbo = 'Mean round-trip length of home-based other trips produced in the zone (miles).',
    productions_nhb = 'Mean round-trip length of non-home-based trips produced in the zone (miles).',
    attractions_hbw = 'Mean round-trip length of home-based work trips attracted to the zone (miles).',
    attractions_hbo = 'Mean round-trip length of home-based other trips attracted to the zone (miles).',
    attractions_nhb = 'Mean round-trip length of non-home-based trips attracted to the zone (miles).'
  ),
  gateway duckdb,
  dialect duckdb,
  columns (
    geometry GEOMETRY,
    productions_hbw DOUBLE,
    productions_hbo DOUBLE,
    productions_nhb DOUBLE,
    attractions_hbw DOUBLE,
    attractions_hbo DOUBLE,
    attractions_nhb DOUBLE
  ),
  blueprints @workspace_blueprints('package_trip_zones')
);

-- Packaged trip-length zones — the ``trip_length_zones`` part of the package a
-- workspace was imported from (``Workspace.trip_length_source = package``).
-- workspace_inputs/trip_zones_package_raw.sql re-tags and projects them for
-- trip_lengths.

SELECT
    ST_SetCRS(geometry, 'EPSG:4326') AS geometry,
    productions_hbw::DOUBLE AS productions_hbw,
    productions_hbo::DOUBLE AS productions_hbo,
    productions_nhb::DOUBLE AS productions_nhb,
    attractions_hbw::DOUBLE AS attractions_hbw,
    attractions_hbo::DOUBLE AS attractions_hbo,
    attractions_nhb::DOUBLE AS attractions_nhb
FROM read_parquet(@trip_length_zones_parquet);
