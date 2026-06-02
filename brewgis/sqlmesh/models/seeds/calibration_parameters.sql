MODEL (
  name brewgis.seeds.calibration_parameters,
  kind SEED (
    path '../../seeds/calibration_parameters.csv'
  ),
  columns (
    land_development_category TEXT,
    sqft_per_du TEXT,
    sqft_per_emp TEXT,
    res_irrigation_frac TEXT,
    com_irrigation_frac TEXT,
    intersection_density TEXT
  )
);
