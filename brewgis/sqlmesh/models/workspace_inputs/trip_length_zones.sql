MODEL (
  name brewgis.@{workspace_schema}.trip_length_zones,
  kind FULL,
  description 'Reference trip-length zones of the workspace (those its package shipped; none for a gravity workspace), projected to the workspace CRS and indexed: the zones trip_lengths assigns each parcel centroid to.',
  column_descriptions (
    geometry = 'Zone polygon (EPSG:4326).',
    local_geometry = 'Zone polygon in the workspace CRS (Workspace.local_srid), GiST-indexed for the centroid containment trip_lengths probes.',
    productions_hbw = 'Mean round-trip length of home-based work trips produced in the zone (miles).',
    productions_hbo = 'Mean round-trip length of home-based other trips produced in the zone (miles).',
    productions_nhb = 'Mean round-trip length of non-home-based trips produced in the zone (miles).',
    attractions_hbw = 'Mean round-trip length of home-based work trips attracted to the zone (miles).',
    attractions_hbo = 'Mean round-trip length of home-based other trips attracted to the zone (miles).',
    attractions_nhb = 'Mean round-trip length of non-home-based trips attracted to the zone (miles).'
  ),
  columns (
    geometry GEOMETRY(MULTIPOLYGON, 4326),
    local_geometry GEOMETRY,
    productions_hbw DOUBLE PRECISION,
    productions_hbo DOUBLE PRECISION,
    productions_nhb DOUBLE PRECISION,
    attractions_hbw DOUBLE PRECISION,
    attractions_hbo DOUBLE PRECISION,
    attractions_nhb DOUBLE PRECISION
  ),
  blueprints @workspace_blueprints()
);

-- Trip-length zones — what trip_lengths reads for every workspace
-- (``brewgis.@{workspace_schema}.trip_length_zones``). The source is the
-- workspace's ``trip_length_source``, resolved to the input model this reads
-- (``trip_length_input``):
--
--   * ``package`` — workspace_inputs/trip_zones_package_raw.sql: the zones
--     the workspace's package shipped (e.g. the SACOG v1 snapshot's SACSIM
--     zones);
--   * ``gravity`` — workspace_inputs/trip_zones_none.sql: no zones, so
--     every parcel keeps the gravity model's length rescaled to the target
--     regional mean (models/python/trip_lengths.py).
--
-- One model over either source, for the reason workspace_inputs/constraint_layers.sql
-- gives. The zones are projected here, once, into the CRS the scenario's
-- ``core_end_state.centroid_local`` is in, behind a GiST index, so the
-- per-parcel containment probe is index-driven. ``ST_SetSRID`` re-tags the
-- package bridge's SRID-less geometry.

SELECT
    ST_Multi(ST_SetSRID(geometry, 4326))::GEOMETRY(MULTIPOLYGON, 4326) AS geometry,
    ST_Transform(ST_Multi(ST_SetSRID(geometry, 4326)), @workspace_srid()) AS local_geometry,
    productions_hbw,
    productions_hbo,
    productions_nhb,
    attractions_hbw,
    attractions_hbo,
    attractions_nhb
FROM brewgis.@{workspace_schema}.@{trip_length_input};

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_trip_length_zones_local_geometry_')
  ON @this_model USING GIST (local_geometry);
ANALYZE @this_model;
