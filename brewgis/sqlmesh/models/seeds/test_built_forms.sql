MODEL (
  name brewgis.seeds.test_built_forms,
  kind SEED (
    path '../../seeds/test_built_forms.csv'
  ),
  columns (
    built_form_key TEXT,
    description TEXT,
    density_category TEXT
  )
);
