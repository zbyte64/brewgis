MODEL (
  name brewgis.tests.test_stage_wac_blocks,
  kind VIEW,
  audits (
    not_null(columns := (geoid))
  )
);

-- Test staging model: produces output matching wac_block schema
-- from the test_wac_block seed data.

SELECT
    geoid,
    emp::double precision AS emp,
    emp_retail_services::double precision AS emp_retail_services,
    emp_restaurant::double precision AS emp_restaurant,
    emp_accommodation::double precision AS emp_accommodation,
    emp_arts_entertainment::double precision AS emp_arts_entertainment,
    emp_other_services::double precision AS emp_other_services,
    emp_office_services::double precision AS emp_office_services,
    emp_medical_services::double precision AS emp_medical_services,
    emp_public_admin::double precision AS emp_public_admin,
    emp_education::double precision AS emp_education,
    emp_manufacturing::double precision AS emp_manufacturing,
    emp_wholesale::double precision AS emp_wholesale,
    emp_transport_warehousing::double precision AS emp_transport_warehousing,
    emp_utilities::double precision AS emp_utilities,
    emp_construction::double precision AS emp_construction,
    emp_agriculture::double precision AS emp_agriculture,
    emp_extraction::double precision AS emp_extraction,
    emp_military::double precision AS emp_military,
    emp_ret::double precision AS emp_ret,
    emp_off::double precision AS emp_off,
    emp_pub::double precision AS emp_pub,
    emp_ind::double precision AS emp_ind,
    emp_ag::double precision AS emp_ag,
    geometry
FROM brewgis.seeds.test_wac_block;
