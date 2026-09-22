MODEL (
  name brewgis.seeds.assessor_use_codes,
  kind SEED (
    path '../../seeds/assessor_use_codes.csv'
  ),
  description 'Assessor use code to land development category lookup used by the base canvas models.',
  column_descriptions (
    use_code = 'Assessor use code to match (text).',
    category = 'Land development category assigned to the use code.'
  ),
  columns (
    use_code TEXT,
    category TEXT
  )
);
