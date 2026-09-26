"""Contract: a map layer's result view exposes the parcel geometry.

The Layers panel registers a layer for every table an analysis run publishes in
its result schema (``workspace.analysis.pipeline.run_modules_sync``), and the
map tiles those layers through Martin, which can only publish a source that has
a geometry column. ``mode_choice``, ``trip_distribution``, ``internal_capture``
and ``total_ghg`` projected only their metric columns, so Martin published no
source for any of them: the layers drew nothing on the map while their rows
still showed in the attribute table.

Scope is the result tables the registry knows a headline map metric for
(``module_registry.TABLE_PRIMARY_COLUMN``) — the workspace-level
``scenario_summary`` is an aggregate with no per-parcel rows and no geometry to
draw.

The first test checks the published views through SQLMesh's own loaded models,
not the model files: what has to carry the geometry is the *published view*, and
for a Python model (whose DataFrame output cannot be a PostGIS geometry) that is
the view's own statement. The other two materialize the models whose geometry is
newly projected *into* their own output — a view built by ``SELECT *`` can only
expose what the model writes, and ``internal_capture`` is the one model that
projected a column nothing had ever materialized before.
"""

from __future__ import annotations

import shutil
import tempfile

import numpy as np
import pandas as pd
import pytest
from sqlglot import exp

from brewgis.workspace.analysis.module_registry import TABLE_PRIMARY_COLUMN
from brewgis.workspace.analysis.sqlmesh_runner import get_context
from tests.dbt_math.sqlmesh_model_runner import run_model

pytestmark = [
    pytest.mark.integration,
    pytest.mark.slow,
    # transaction=True so the parity fixture's committed blueprint rows are
    # visible to SQLMesh's forked model-loading workers.
    pytest.mark.django_db(transaction=True),
]

_WKT = "POLYGON((0 0, 0 1, 1 1, 1 0, 0 0))"


def _published_view_columns(model: object) -> set[str]:
    """The columns the model's published result view exposes."""
    columns = set(getattr(model, "columns_to_types", None) or {})
    for statement in getattr(model, "on_virtual_update", None) or []:
        query = statement.expression if isinstance(statement, exp.Create) else None
        if not isinstance(query, exp.Query):
            continue
        for projection in query.selects:
            if isinstance(projection, exp.Star):
                # ``SELECT *`` over the model's table: the view exposes that
                # table's own columns, which are already counted.
                continue
            columns.add(projection.alias_or_name)
    return columns


def test_every_map_layer_result_view_exposes_geometry(parity_scenario: str) -> None:
    """Every parcel-level result view a run publishes is a tileable map layer."""
    cache_dir = tempfile.mkdtemp(prefix="brewgis-result-view-geometry-")
    context = get_context(cache_dir=cache_dir)
    try:
        missing = {}
        for table in sorted(TABLE_PRIMARY_COLUMN):
            model = context.get_model(f"brewgis.{parity_scenario}.{table}")
            columns = _published_view_columns(model)
            if "geometry" not in columns:
                missing[table] = sorted(columns)
    finally:
        for adapter in (context.engine_adapters or {}).values():
            adapter.close()
        context.close()
        shutil.rmtree(cache_dir, ignore_errors=True)

    assert not missing, (
        "these result views are registered as parcel map layers but publish no"
        " geometry column, so Martin publishes no tile source for them and the"
        f" layer draws nothing: {missing}"
    )


def test_internal_capture_materializes_with_geometry(parity_scenario: str) -> None:
    """``internal_capture`` runs at all, and its output carries the parcel geometry.

    It had never materialized: its three ``ROUND`` calls took ``double
    precision`` arguments (``round(double precision, int)`` does not exist), so
    the model failed before producing a row — which also means its newly
    projected geometry was never written.
    """
    parcel_id = np.arange(3, dtype=int)
    trips_total = np.array([0.0, 100.0, 250.0])
    trips_intra_parcel = np.array([0.0, 1.0, 2.0])
    trips_outbound = np.array([0.0, 90.0, 200.0])

    result = run_model(
        "internal_capture",
        upstream={
            "trip_generation": pd.DataFrame(
                {
                    "parcel_id": parcel_id,
                    "trips_total": trips_total,
                    "trips_res": np.array([0.0, 60.0, 150.0]),
                    "trips_nonres": np.array([0.0, 40.0, 100.0]),
                    "geometry": np.full(3, _WKT),
                }
            ),
            "trip_distribution": pd.DataFrame(
                {
                    "parcel_id": parcel_id,
                    "trips_internal": trips_intra_parcel,
                    "trips_outbound": trips_outbound,
                    "trips_inbound": np.array([0.0, 90.0, 200.0]),
                    "avg_trip_length_km": np.array([0.0, 8.0, 12.0]),
                }
            ),
            "core_end_state": pd.DataFrame(
                {"parcel_id": parcel_id, "geometry": np.full(3, _WKT)}
            ),
        },
        scenario_schema=parity_scenario,
    )

    assert result["geometry"].notna().all()
    # External trips are measured from the parcel's *total* trips (an inbound
    # count would answer a different question) and never go negative. The
    # tolerance covers the 4 decimals the model rounds ``internal_capture_pct``
    # to in its output: it computes with the unrounded value.
    capture_pct = result["internal_capture_pct"].astype(float).to_numpy()
    assert result["trips_external"].to_numpy() == pytest.approx(
        np.maximum(
            0.0, trips_total - trips_intra_parcel - trips_outbound * capture_pct
        ),
        abs=0.05,
    )


def test_total_ghg_materializes_with_geometry(parity_scenario: str) -> None:
    """``total_ghg`` carries the geometry of whichever parent has the parcel."""
    parcel_id = np.array([1, 2], dtype=int)

    result = run_model(
        "total_ghg",
        upstream={
            "transport_ghg": pd.DataFrame(
                {
                    "parcel_id": parcel_id,
                    "co2e_total_kg": np.array([1.0, 2.0]),
                    "geometry": np.full(2, _WKT),
                }
            ),
            "building_water_ghg": pd.DataFrame(
                {
                    "parcel_id": parcel_id,
                    "co2e_energy_total_kg": np.array([3.0, 4.0]),
                    "co2e_water_total_kg": np.array([5.0, 6.0]),
                    "co2e_total_kg": np.array([8.0, 10.0]),
                    "geometry": np.full(2, _WKT),
                }
            ),
        },
        scenario_schema=parity_scenario,
    )

    assert result["geometry"].notna().all()
    assert result["co2e_total"].tolist() == pytest.approx([9.0, 12.0])
