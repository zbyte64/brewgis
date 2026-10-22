MODEL (
  name brewgis.@{workspace_schema}.trip_zones_none,
  kind FULL,
  description 'No reference trip-length zones: the empty zone source of a workspace whose trip lengths come from the gravity model.',
  column_descriptions (
    geometry = 'Zone polygon (EPSG:4326); no rows.',
    productions_hbw = 'Mean round-trip length of home-based work trips produced in the zone (miles); no rows.',
    productions_hbo = 'Mean round-trip length of home-based other trips produced in the zone (miles); no rows.',
    productions_nhb = 'Mean round-trip length of non-home-based trips produced in the zone (miles); no rows.',
    attractions_hbw = 'Mean round-trip length of home-based work trips attracted to the zone (miles); no rows.',
    attractions_hbo = 'Mean round-trip length of home-based other trips attracted to the zone (miles); no rows.',
    attractions_nhb = 'Mean round-trip length of non-home-based trips attracted to the zone (miles); no rows.'
  ),
  columns (
    geometry GEOMETRY,
    productions_hbw DOUBLE PRECISION,
    productions_hbo DOUBLE PRECISION,
    productions_nhb DOUBLE PRECISION,
    attractions_hbw DOUBLE PRECISION,
    attractions_hbo DOUBLE PRECISION,
    attractions_nhb DOUBLE PRECISION
  ),
  blueprints @workspace_blueprints('gravity_trip_zones')
);

-- A gravity workspace's trip-length zone source: none.
-- workspace_inputs/trip_length_zones.sql reads it like any other source, so
-- trip_lengths' dependency has the same shape whatever the workspace ships.

SELECT
    NULL::GEOMETRY AS geometry,
    NULL::DOUBLE PRECISION AS productions_hbw,
    NULL::DOUBLE PRECISION AS productions_hbo,
    NULL::DOUBLE PRECISION AS productions_nhb,
    NULL::DOUBLE PRECISION AS attractions_hbw,
    NULL::DOUBLE PRECISION AS attractions_hbo,
    NULL::DOUBLE PRECISION AS attractions_nhb
WHERE FALSE;
