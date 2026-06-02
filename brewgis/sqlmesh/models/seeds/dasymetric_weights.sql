MODEL (
  name brewgis.seeds.dasymetric_weights,
  kind SEED (
    path '../../seeds/dasymetric_weights.csv'
  ),
  columns (
    land_development_category TEXT,
    pop_mult DOUBLE PRECISION,
    emp_mult DOUBLE PRECISION
  )
);
