#!/usr/bin/env bash
# Run the dbt seed → run → test pipeline for CI.
# Tests base_canvas_geometry (geometry parsing + area computation) using
# seed test data.  Full-chain ACS/LEHD-dependent models are covered by
# integration tests with real data.
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
