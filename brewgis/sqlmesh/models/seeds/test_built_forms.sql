MODEL (
  name brewgis.seeds.test_built_forms,
  kind SEED (
    path '../../seeds/test_built_forms.csv'
  ),
  description 'Test fixture: 3 built form keys, each with a description and density category.',
  column_descriptions (
    built_form_key = 'Built form key being defined.',
    description = 'Human-readable description of the built form.',
    density_category = 'Density category of the built form (urban, compact or standard).'
  ),
  columns (
    built_form_key TEXT,
    description TEXT,
    density_category TEXT
  )
);
