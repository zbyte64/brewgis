MODEL (
  name brewgis.seeds.assessor_use_codes,
  kind SEED (
    path '../../seeds/assessor_use_codes.csv'
  ),
  columns (
    use_code TEXT,
    category TEXT
  )
);
