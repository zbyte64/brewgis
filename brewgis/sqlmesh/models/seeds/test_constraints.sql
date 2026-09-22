MODEL (
  name brewgis.seeds.test_constraints,
  kind SEED (
    path '../../seeds/test_constraints.csv'
  ),
  description 'Test fixture: 1 constraint polygon with a type label and a buffer distance.',
  column_descriptions (
    constraint_id = 'Identifier of the constraint polygon (integer).',
    geometry = 'Constraint polygon geometry in EPSG:4326 (WGS 84).',
    constraint_type = 'Type of constraint the polygon represents (floodplain in the fixture).',
    buffer_distance = 'Distance the constraint geometry is buffered by before it is overlaid.'
  ),
  columns (
    constraint_id INTEGER,
    geometry geometry(Geometry,4326),
    constraint_type TEXT,
    buffer_distance DOUBLE PRECISION
  )
);
