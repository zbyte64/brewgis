"""Integration tests: run actual SQLMesh models, compare to Python references.

Each test:
1. Generates synthetic upstream data as DataFrames
2. Writes it to temp PostGIS tables via ``run_model()``
3. Invokes dbt-core's Python API to compile and run the model
4. Reads the output table
5. Compares to the Python reference function's output

No SQL is duplicated — the dbt model files are the single source of truth.
"""
# ruff: noqa: ANN201
# mypy: ignore-errors

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tests.dbt_math.reference import compute_mode_choice
from tests.dbt_math.reference import compute_property_tax
from tests.dbt_math.reference import compute_service_costs
from tests.dbt_math.reference import compute_transport_ghg
from tests.dbt_math.reference import compute_vmt
from tests.dbt_math.sqlmesh_model_runner import run_model

pytestmark = [
    pytest.mark.integration,
    # transaction=True so the `parity_scenario` fixture's committed rows are
    # visible to SQLMesh's forked model-loading workers, and flushed after.
    pytest.mark.django_db(transaction=True),
    # These tests cannot run against the Django test database, and the reason is
    # structural rather than a missing fixture: `brewgis/sqlmesh/config.py`
    # builds its connection from `DATABASE_URL` (the live `brewgis` database),
    # while the project's models are named `brewgis.<schema>.<table>` — for
    # Postgres that first part is a *catalog*, and SQLMesh refuses to run a plan
    # whose catalog differs from the connected one ("postgres requires that all
    # catalog operations be against a single catalog: test_brewgis. Provided
    # catalog: brewgis"). Renaming the connection's database to `test_brewgis`
    # (which `conftest.py` does, so the suite at least touches the right
    # database) hits exactly that check.
    #
    # The bodies below are kept current with the models' contracts (they are the
    # comparison against `tests/dbt_math/reference.py`), and they run as soon as
    # a `brewgis`-named database is what this harness plans into — which is how
    # the repo verifies SQLMesh itself (`make test-sqlmesh` and
    # `make plan-base` both run the CLI against the live stack).
    pytest.mark.skip(
        reason=(
            "SQLMesh plans require a database named 'brewgis'; the Django test "
            "database is 'test_brewgis' (catalog mismatch). Verify the SQL side "
            "via the live stack instead: run the module and compare the "
            "materialized rows against tests/dbt_math/reference.py."
        )
    ),
]


def _core_es_df(
    parcel_id: np.ndarray,
    du: np.ndarray | None = None,
    pop: np.ndarray | None = None,
    emp: np.ndarray | None = None,
    building_sqft_total: np.ndarray | None = None,
    **extra: np.ndarray,
) -> pd.DataFrame:
    """Build a synthetic ``core_end_state`` DataFrame with the model's real columns.

    Only the columns the analysis models actually read are filled in — these are
    the names ``core_end_state`` writes today (``du``/``emp``/``pop``, not the
    pre-SQLMesh ``dwelling_units_total``/``employment_total``/``population``).
    ``geometry`` is WKT, written as a PostGIS geometry column by ``_write_df``,
    because a model that copies it into its own output indexes it with GIST.
    """
    n = len(parcel_id)
    data = {
        "parcel_id": parcel_id,
        "du": du if du is not None else np.full(n, 50.0),
        "pop": pop if pop is not None else np.full(n, 100.0),
        "emp": emp if emp is not None else np.full(n, 20.0),
        "building_sqft_total": (
            building_sqft_total if building_sqft_total is not None else np.full(n, 1e4)
        ),
        "area_gross_acres": np.full(n, 1.0),
        "land_development_category": np.full(n, "urban"),
        "intersection_density": np.full(n, 5.0),
        "geometry": np.full(n, "POINT(0 0)"),
    }
    data.update(extra)
    return pd.DataFrame(data)


# ══════════════════════════════════════════════════════════════════════
#  Fiscal — Property Tax
# ══════════════════════════════════════════════════════════════════════


@pytest.mark.slow
def test_fiscal_property_tax_parity(parity_scenario: str) -> None:
    """dbt fiscal_property_tax output matches Python reference."""
    du = np.array([0.0, 5.0, 100.0, 2.5], dtype=float)
    bsqt = np.array([0.0, 2000.0, 50000.0, 100.0], dtype=float)
    pid = np.arange(len(du), dtype=int)

    av_ref, an_ref, rev_ref = compute_property_tax(du, bsqt)

    es_df = _core_es_df(pid, du=du, building_sqft_total=bsqt)
    result = run_model(
        "fiscal_property_tax",
        upstream={"core_end_state": es_df},
        scenario_schema=parity_scenario,
    )

    assert np.allclose(result["assessed_value_res"], av_ref, atol=1e-3)
    assert np.allclose(result["assessed_value_nonres"], an_ref, atol=1e-3)
    assert np.allclose(result["property_tax_revenue"], rev_ref, atol=1e-3)
    assert len(result) == len(du)


# ══════════════════════════════════════════════════════════════════════
#  Fiscal — Service Costs
# ══════════════════════════════════════════════════════════════════════


@pytest.mark.slow
def test_fiscal_service_costs_parity(parity_scenario: str) -> None:
    """dbt fiscal_service_costs output matches Python reference."""
    du = np.array([0.0, 5.0, 100.0], dtype=float)
    pop = np.array([0.0, 10.0, 250.0], dtype=float)
    emp = np.array([0.0, 3.0, 50.0], dtype=float)
    pid = np.arange(len(du), dtype=int)

    s_ref, ps_ref, r_ref, t_ref = compute_service_costs(du, pop, emp)

    es_df = _core_es_df(pid, du=du, pop=pop, emp=emp)
    result = run_model(
        "fiscal_service_costs",
        upstream={"core_end_state": es_df},
        scenario_schema=parity_scenario,
    )

    assert np.allclose(result["service_cost_schools"], s_ref, atol=1e-3)
    assert np.allclose(result["service_cost_public_safety"], ps_ref, atol=1e-3)
    assert np.allclose(result["service_cost_roads"], r_ref, atol=1e-3)
    assert np.allclose(result["service_cost_total"], t_ref, atol=1e-3)


# ══════════════════════════════════════════════════════════════════════
#  Mode Choice
# ══════════════════════════════════════════════════════════════════════


@pytest.mark.slow
def test_mode_choice_parity(parity_scenario: str) -> None:
    """SQLMesh mode_choice output matches the Python reference."""
    trips = np.array([0.0, 100.0, 250.0, 40.0], dtype=float)
    du = np.array([0.0, 10.0, 40.0, 5.0], dtype=float)
    area = np.array([1.0, 0.5, 4.0, 2.0], dtype=float)
    intersection_density = np.array([0.0, 5.0, 30.0, 2.0], dtype=float)
    categories = np.array(["rural", "urban", "compact", "standard"], dtype=object)
    pid = np.arange(len(trips), dtype=int)

    density = np.where(area > 0, du / area, 0.0)
    transit_access = np.where(np.isin(categories, ["urban", "compact"]), 1.0, 0.0)
    reference = compute_mode_choice(
        trips, density, intersection_density, transit_access
    )

    td_df = pd.DataFrame({"parcel_id": pid, "trips_outbound": trips})
    es_df = _core_es_df(
        pid,
        du=du,
        area_gross_acres=area,
        intersection_density=intersection_density,
        land_development_category=categories,
    )

    result = run_model(
        "mode_choice",
        upstream={"trip_distribution": td_df, "core_end_state": es_df},
        scenario_schema=parity_scenario,
    )

    columns = (
        "trips_auto",
        "trips_transit",
        "trips_walk",
        "trips_bike",
        "mode_share_auto",
        "mode_share_transit",
        "mode_share_walk",
        "mode_share_bike",
    )
    for column, expected in zip(columns, reference, strict=True):
        assert np.allclose(result[column], expected, atol=1e-8), column


# ══════════════════════════════════════════════════════════════════════
#  VMT
# ══════════════════════════════════════════════════════════════════════


@pytest.mark.slow
def test_vmt_parity(parity_scenario: str) -> None:
    """SQLMesh VMT output matches the Python reference."""
    auto_trips = np.array([0.0, 85.0, 425.0], dtype=float)
    avg_trip_length_km = np.array([0.0, 8.0, 12.0], dtype=float)
    pop = np.array([0.0, 10.0, 250.0], dtype=float)
    pid = np.arange(len(auto_trips), dtype=int)

    v_ref, vpc_ref, tl_ref, _ = compute_vmt(auto_trips, avg_trip_length_km, pop)

    # VMT now reads the mode-choice auto trips and the trip-distribution
    # average trip length.
    mc_df = pd.DataFrame({"parcel_id": pid, "trips_auto": auto_trips})
    td_df = pd.DataFrame({"parcel_id": pid, "avg_trip_length_km": avg_trip_length_km})
    es_df = _core_es_df(pid, pop=pop)

    result = run_model(
        "vmt",
        upstream={
            "mode_choice": mc_df,
            "trip_distribution": td_df,
            "core_end_state": es_df,
        },
        scenario_schema=parity_scenario,
    )

    assert np.allclose(result["auto_trips"], auto_trips, atol=1e-8)
    assert np.allclose(result["vmt_total"], v_ref, atol=1e-3)
    assert np.allclose(result["vmt_per_capita"], vpc_ref, atol=1e-3)
    assert np.allclose(result["avg_trip_length_mi"], tl_ref, atol=1e-6)


# ══════════════════════════════════════════════════════════════════════
#  Transport GHG
# ══════════════════════════════════════════════════════════════════════


@pytest.mark.slow
def test_transport_ghg_parity(parity_scenario: str) -> None:
    """dbt transport_ghg output matches Python reference."""
    vmt = np.array([0.0, 500.0, 2000.0], dtype=float)
    pop = np.array([0.0, 10.0, 250.0], dtype=float)
    pid = np.arange(len(vmt), dtype=int)

    co2e_ref, pc_ref = compute_transport_ghg(vmt, pop)

    vmt_df = pd.DataFrame(
        {
            "parcel_id": pid,
            "vmt_total": vmt,
            "vmt_per_capita": np.where(pop > 0, vmt / pop, 0.0),
            "avg_trip_length_mi": np.full(len(vmt), 5.0),
            "auto_trips": np.full(len(vmt), 100.0),
        }
    )
    es_df = _core_es_df(pid, pop=pop)

    result = run_model(
        "transport_ghg",
        upstream={"vmt": vmt_df, "core_end_state": es_df},
        scenario_schema=parity_scenario,
    )

    assert np.allclose(result["co2e_total_kg"], co2e_ref, atol=1e-3)
    assert np.allclose(result["co2e_per_capita_kg"], pc_ref, atol=1e-3)
