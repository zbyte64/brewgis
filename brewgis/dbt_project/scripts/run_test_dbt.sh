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

DBT_VARS='{"parcel_table": "test_parcels", "built_form_table": "test_built_forms", "constraint_table": "test_constraints", "base_canvas_table": "test_base_canvas", "projected_srid": 32610, "scenario_id": "test"}'
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
echo "=== dbt run (full sacog chain: geometry + demographics + employment + attributes) ==="
CHAIN_VARS='{"parcel_table": "sacog_parcel_shim", "acs_block_group_table": "test_acs_block_group", "wac_block_table": "test_wac_block", "projected_srid": 32610, "scenario_id": "test"}'
dbt run --profiles-dir . --select base_canvas_geometry base_canvas_demographics base_canvas_employment base_canvas_attributes --vars "$CHAIN_VARS"

echo ""
echo "=== dbt test (base_canvas_attributes) ==="
dbt test --profiles-dir . --select base_canvas_attributes --vars "$CHAIN_VARS"
