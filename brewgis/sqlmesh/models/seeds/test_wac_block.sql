MODEL (
  name brewgis.seeds.test_wac_block,
  kind SEED (
    path '../../seeds/test_wac_block.csv'
  ),
  columns (
    geoid TEXT,
    emp INTEGER,
    emp_retail_services INTEGER,
    emp_restaurant INTEGER,
    emp_accommodation INTEGER,
    emp_arts_entertainment INTEGER,
    emp_other_services INTEGER,
    emp_office_services INTEGER,
    emp_medical_services INTEGER,
    emp_public_admin INTEGER,
    emp_education INTEGER,
    emp_manufacturing INTEGER,
    emp_wholesale INTEGER,
    emp_transport_warehousing INTEGER,
    emp_utilities INTEGER,
    emp_construction INTEGER,
    emp_agriculture INTEGER,
    emp_extraction INTEGER,
    emp_military INTEGER,
    emp_ret INTEGER,
    emp_off INTEGER,
    emp_pub INTEGER,
    emp_ind INTEGER,
    emp_ag INTEGER,
    geometry geometry(Geometry,4326)
  )
);
