MODEL (
  name brewgis.seeds.test_wac_block,
  kind SEED (
    path '../../seeds/test_wac_block.csv'
  ),
  columns (
    geoid TEXT,
    emp TEXT,
    emp_retail_services TEXT,
    emp_restaurant TEXT,
    emp_accommodation TEXT,
    emp_arts_entertainment TEXT,
    emp_other_services TEXT,
    emp_office_services TEXT,
    emp_medical_services TEXT,
    emp_public_admin TEXT,
    emp_education TEXT,
    emp_manufacturing TEXT,
    emp_wholesale TEXT,
    emp_transport_warehousing TEXT,
    emp_utilities TEXT,
    emp_construction TEXT,
    emp_agriculture TEXT,
    emp_extraction TEXT,
    emp_military TEXT,
    emp_ret TEXT,
    emp_off TEXT,
    emp_pub TEXT,
    emp_ind TEXT,
    emp_ag TEXT,
    geometry geometry(Geometry,4326)
  )
);
