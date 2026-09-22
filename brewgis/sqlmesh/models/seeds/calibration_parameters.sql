MODEL (
  name brewgis.seeds.calibration_parameters,
  kind SEED (
    path '../../seeds/calibration_parameters.csv'
  ),
  description 'Per-category calibration constants: square feet per unit, irrigation fraction, intersection density.',
  column_descriptions (
    land_development_category = 'Land development category the calibration constants apply to.',
    sqft_per_du = 'Calibrated building area per dwelling unit for the category (sq ft per DU).',
    sqft_per_emp_retail = 'Calibrated building area per retail employee (sq ft per job).',
    sqft_per_emp_office = 'Calibrated building area per office employee (sq ft per job).',
    sqft_per_emp_public = 'Calibrated building area per public employee (sq ft per job).',
    sqft_per_emp_industrial = 'Calibrated building area per industrial employee (sq ft per job).',
    res_irrigation_frac = 'Fraction of residential outdoor area assumed irrigated (0-1).',
    com_irrigation_frac = 'Fraction of commercial outdoor area assumed irrigated (0-1).',
    intersection_density = 'Calibrated intersection density for the category (intersections per km2).'
  ),
  columns (
    land_development_category TEXT,
    sqft_per_du DOUBLE PRECISION,
    sqft_per_emp_retail DOUBLE PRECISION,
    sqft_per_emp_office DOUBLE PRECISION,
    sqft_per_emp_public DOUBLE PRECISION,
    sqft_per_emp_industrial DOUBLE PRECISION,
    res_irrigation_frac DOUBLE PRECISION,
    com_irrigation_frac DOUBLE PRECISION,
    intersection_density DOUBLE PRECISION
  )
);
