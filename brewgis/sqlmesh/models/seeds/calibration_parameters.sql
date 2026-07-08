MODEL (
  name brewgis.seeds.calibration_parameters,
  kind SEED (
    path '../../seeds/calibration_parameters.csv'
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
