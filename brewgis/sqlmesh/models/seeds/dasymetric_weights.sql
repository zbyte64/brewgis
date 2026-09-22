MODEL (
  name brewgis.seeds.dasymetric_weights,
  kind SEED (
    path '../../seeds/dasymetric_weights.csv'
  ),
  description 'Dasymetric population and employment multipliers per land development category.',
  column_descriptions (
    land_development_category = 'Land development category the multipliers apply to.',
    pop_mult = 'Population multiplier applied to the category in dasymetric allocation.',
    emp_mult = 'Employment multiplier applied to the category in dasymetric allocation.'
  ),
  columns (
    land_development_category TEXT,
    pop_mult DOUBLE PRECISION,
    emp_mult DOUBLE PRECISION
  )
);
