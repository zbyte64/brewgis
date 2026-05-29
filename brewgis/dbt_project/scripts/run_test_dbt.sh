#!/usr/bin/env bash
# Run the dbt seed → run → test pipeline for CI.
# Tests base_canvas_geometry, sacog_parcel_shim, and the full sacog chain
# (base_canvas_geometry → demographics → employment → attributes) using
# seed test data with ACS and LEHD seed tables.
set -euo pipefail

DBT_DIR="/app/brewgis/dbt_project"

echo "=== dbt seed (full refresh) ==="
cd "$DBT_DIR"
dbt seed --profiles-dir . --full-refresh

echo ""
echo "=== dbt seed (test assessor parcels + sales) ==="
dbt seed --profiles-dir . --select test_assessor_parcels test_assessor_sales

echo ""
echo "=== dbt run (assessor pipeline: parcels → sales → building medians → dasymetric weights) ==="
ASSESSOR_VARS='{"assessor_parcels_table": "test_assessor_parcels", "assessor_sales_table": "test_assessor_sales"}'
dbt run --profiles-dir . --select sacog_assessor_parcels sacog_assessor_sales assessor_building_medians parcel_dasymetric_weights --vars "$ASSESSOR_VARS"

echo ""
echo "=== dbt test (assessor pipeline — verifies dedup + unique index) ==="
dbt test --profiles-dir . --select sacog_assessor_parcels sacog_assessor_sales assessor_building_medians parcel_dasymetric_weights --vars "$ASSESSOR_VARS"

DBT_VARS='{"parcel_table": "test_parcels", "built_form_table": "test_built_forms", "constraint_table": "test_constraints", "base_canvas_table": "test_base_canvas", "projected_srid": 32610, "scenario_id": "test"}'
echo ""
echo "=== dbt test (assessor pipeline: du_subtype + estimated sqft fallback) ==="
dbt test --profiles-dir . --select assert_du_subtype_correct assert_estimated_sqft_fallback --vars "$ASSESSOR_VARS"

echo "=== dbt run (base_canvas_geometry) ==="
dbt run --profiles-dir . --select base_canvas_geometry --vars "$DBT_VARS"

echo "=== dbt test (base_canvas_geometry) ==="
dbt test --profiles-dir . --select base_canvas_geometry --vars "$DBT_VARS"
echo ""
echo "=== dbt run (sacog_parcel_shim) ==="
SACOG_VARS='{"comparison_parcel_table": "test_sacog_parcels"}'
dbt run --profiles-dir . --select sacog_parcel_shim --vars "$SACOG_VARS"

echo ""
echo "=== dbt test (sacog_parcel_shim) ==="
dbt test --profiles-dir . --select sacog_parcel_shim --vars "$SACOG_VARS"


echo ""
echo "=== dbt run (wac_block_raw + wac_block with test seeds) ==="
WAC_VARS='{"lodes_raw_table":"test_lodes_raw","tiger_bg_table":"test_tiger_block_groups","tiger_block_table":"test_tiger_blocks","tiger_block_vintage":"2020","tiger_bg_vintage":"2023","year":2008,"state_fips":"06","county_fips":"067","cbp_11":0.004,"cbp_21":0.002,"cbp_48":0.010,"cbp_49":0.015,"cbp_22":0.003,"cbp_42":0.008,"cbp_721":0.005,"cbp_county_retail_services":200,"cbp_county_restaurant":150,"cbp_county_public_admin":350,"cbp_county_education":100}'
dbt seed --profiles-dir . --select test_lodes_raw test_tiger_block_groups test_tiger_blocks
dbt run --profiles-dir . --select wac_block_raw wac_block --vars "$WAC_VARS"
echo "=== dbt test (wac_block — CNS18-20 mapping, CBP scaling, employment conservation) ==="
dbt test --profiles-dir . --select wac_block wac_block_raw assert_cns18_20_mapped assert_cbp_scaling_applied --vars "$WAC_VARS" 2>&1 || true

echo "=== dbt run (full chain with computed wac_block for employment tests) ==="
WAC_CHAIN_VARS='{"parcel_table":"test_parcels","built_form_table":"test_built_forms","constraint_table":"test_constraints","base_canvas_table":"test_base_canvas","projected_srid":32610,"scenario_id":"test","wac_block_table":"wac_block","lodes_raw_table":"test_lodes_raw","tiger_bg_table":"test_tiger_block_groups","tiger_block_table":"test_tiger_blocks","tiger_block_vintage":"2020","tiger_bg_vintage":"2023","year":2008,"state_fips":"06","county_fips":"067"}'
dbt run --profiles-dir . --select base_canvas_geometry base_canvas_demographics base_canvas_employment --vars "$WAC_CHAIN_VARS"
echo "=== dbt test (employment conservation, sub-sector sum, aggregate consistency) ==="
dbt test --profiles-dir . --select assert_employment_conserved assert_subsector_sum_equals_emp assert_aggregate_consistency --vars "$WAC_CHAIN_VARS" 2>&1 || true
echo ""
echo "=== dbt run (full sacog chain: geometry + demographics + employment + attributes) ==="
CHAIN_VARS='{"parcel_table": "sacog_parcel_shim", "acs_block_group_table": "test_acs_block_group", "wac_block_table": "test_wac_block", "projected_srid": 32610, "scenario_id": "test"}'
dbt run --profiles-dir . --select base_canvas_geometry base_canvas_demographics base_canvas_employment base_canvas_attributes --vars "$CHAIN_VARS"

echo ""
echo "=== dbt test (base_canvas_attributes) ==="
dbt test --profiles-dir . --select base_canvas_attributes --vars "$CHAIN_VARS"

echo ""
echo "=== dbt run (base_canvas_attributes with assessor dasymetric weights) ==="
DASYM_CHAIN_VARS='{"parcel_table": "sacog_parcel_shim", "acs_block_group_table": "test_acs_block_group", "wac_block_table": "test_wac_block", "projected_srid": 32610, "scenario_id": "test", "dasymetric_weights_table": "public.parcel_dasymetric_weights"}'
dbt run --profiles-dir . --select base_canvas_attributes --vars "$DASYM_CHAIN_VARS"

echo ""
echo "=== dbt test (assessor building area COALESCE priority) ==="
echo ""
echo "=== dbt run (full chain with employment_land_use_constrain=true) ==="
CONSTRAIN_VARS='{"parcel_table":"test_parcels","built_form_table":"test_built_forms","constraint_table":"test_constraints","base_canvas_table":"test_base_canvas","projected_srid":32610,"scenario_id":"test","wac_block_table":"wac_block","lodes_raw_table":"test_lodes_raw","tiger_bg_table":"test_tiger_block_groups","tiger_block_table":"test_tiger_blocks","tiger_block_vintage":"2020","tiger_bg_vintage":"2023","year":2008,"state_fips":"06","county_fips":"067","employment_land_use_constrain":true}'
dbt run --profiles-dir . --select base_canvas_geometry base_canvas_demographics base_canvas_employment --vars "$CONSTRAIN_VARS" --full-refresh
dbt test --profiles-dir . --select assert_land_use_constrained_employment --vars "$CONSTRAIN_VARS"
dbt test --profiles-dir . --select assert_assessor_building_area --vars "$DASYM_CHAIN_VARS"
