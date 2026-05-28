"""Integration tests: run actual dbt models via dbt-core, compare to Python references.

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

from tests.dbt_math.dbt_model_runner import run_model
from tests.dbt_math.reference import compute_property_tax
from tests.dbt_math.reference import compute_service_costs
from tests.dbt_math.reference import compute_transport_ghg
from tests.dbt_math.reference import compute_vmt

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


def _core_es_df(
    parcel_id: np.ndarray,
    du: np.ndarray | None = None,
    bsqt: np.ndarray | None = None,
    pop: np.ndarray | None = None,
    emp: np.ndarray | None = None,
    hh: np.ndarray | None = None,
    hh_size: np.ndarray | None = None,
    **extra: np.ndarray,
) -> pd.DataFrame:
    """Build a synthetic ``core_end_state`` DataFrame with minimum required columns."""
    n = len(parcel_id)
    data = {
        "parcel_id": parcel_id,
        "gross_acres": np.full(n, 1.0),
        "acres_developed": np.full(n, 0.5),
        "population": pop if pop is not None else np.full(n, 100.0),
        "households": hh if hh is not None else np.full(n, 50.0),
        "household_size": hh_size if hh_size is not None else np.full(n, 2.5),
        "dwelling_units_total": du if du is not None else np.full(n, 50.0),
        "employment_total": emp if emp is not None else np.full(n, 20.0),
        "building_sqft_total": bsqt if bsqt is not None else np.full(n, 10000.0),
        "electricity_eui": np.full(n, 100.0),
        "gas_eui": np.full(n, 50.0),
        "indoor_water_rate": np.full(n, 300.0),
        "outdoor_water_rate": np.full(n, 200.0),
        "res_irrigated_sqft": np.full(n, 1000.0),
        "com_irrigated_sqft": np.full(n, 500.0),
        "intersection_density": np.full(n, 5.0),
        "land_dev_category": np.full(n, "urban"),
        "built_form_id": np.full(n, 1),
        "parcel_acres_developed": np.full(n, 0.5),
        "parcel_acres_agriculture": np.full(n, 0.0),
        "parcel_acres_open_space": np.full(n, 0.0),
        "parcel_acres_vacant": np.full(n, 0.0),
        "vacancy_rate": np.full(n, 5.0),
        "building_coverage": np.full(n, 30.0),
        "irrigable_area_fraction": np.full(n, 0.5),
        "far": np.full(n, 0.5),
        "geom": np.full(n, "POINT(0 0)"),
    }
    data.update(extra)
    return pd.DataFrame(data)


# ══════════════════════════════════════════════════════════════════════
#  Fiscal — Property Tax
# ══════════════════════════════════════════════════════════════════════


@pytest.mark.slow
def test_fiscal_property_tax_parity() -> None:
    """dbt fiscal_property_tax output matches Python reference."""
    du = np.array([0.0, 5.0, 100.0, 2.5], dtype=float)
    bsqt = np.array([0.0, 2000.0, 50000.0, 100.0], dtype=float)
    pid = np.arange(len(du), dtype=int)

    av_ref, an_ref, rev_ref = compute_property_tax(du, bsqt)

    es_df = _core_es_df(pid, du=du, bsqt=bsqt)
    result = run_model(
        "fiscal_property_tax",
        upstream={"core_end_state": es_df},
        vars_={"scenario_id": "test_fpt"},
    )

    assert np.allclose(result["assessed_value_res"], av_ref, atol=1e-3)
    assert np.allclose(result["assessed_value_nonres"], an_ref, atol=1e-3)
    assert np.allclose(result["property_tax_revenue"], rev_ref, atol=1e-3)
    assert len(result) == len(du)


# ══════════════════════════════════════════════════════════════════════
#  Fiscal — Service Costs
# ══════════════════════════════════════════════════════════════════════


@pytest.mark.slow
def test_fiscal_service_costs_parity() -> None:
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
        vars_={"scenario_id": "test_fsc"},
    )

    assert np.allclose(result["service_cost_schools"], s_ref, atol=1e-3)
    assert np.allclose(result["service_cost_public_safety"], ps_ref, atol=1e-3)
    assert np.allclose(result["service_cost_roads"], r_ref, atol=1e-3)
    assert np.allclose(result["service_cost_total"], t_ref, atol=1e-3)


# ══════════════════════════════════════════════════════════════════════
#  VMT
# ══════════════════════════════════════════════════════════════════════


@pytest.mark.slow
def test_vmt_parity() -> None:
    """dbt VMT output matches Python reference."""
    auto = np.array([0.0, 100.0, 500.0], dtype=float)
    length = np.array([0.0, 5.0, 15.0], dtype=float)
    pop = np.array([0.0, 10.0, 250.0], dtype=float)
    pid = np.arange(len(auto), dtype=int)

    v_ref, vpc_ref, tl_ref, _ = compute_vmt(auto, length, pop)

    # VMT depends on mode_choice + trip_distribution + core_end_state
    mc_df = pd.DataFrame(
        {
            "parcel_id": pid,
            "trips_auto": auto,
            "trips_transit": np.zeros(len(auto)),
            "trips_walk": np.zeros(len(auto)),
            "trips_bike": np.zeros(len(auto)),
            "mode_share_auto": np.where(auto > 0, 1.0, 0.0),
            "mode_share_transit": np.zeros(len(auto)),
            "mode_share_walk": np.zeros(len(auto)),
            "mode_share_bike": np.zeros(len(auto)),
        }
    )
    td_df = pd.DataFrame(
        {
            "parcel_id": pid,
            "trips_outbound": auto,
            "trips_inbound": auto,
            "trips_internal": np.zeros(len(auto)),
            "avg_trip_length_km": length,
        }
    )
    es_df = _core_es_df(pid, pop=pop)

    result = run_model(
        "vmt",
        upstream={
            "mode_choice": mc_df,
            "trip_distribution": td_df,
            "core_end_state": es_df,
        },
        vars_={"scenario_id": "test_vmt"},
    )

    assert np.allclose(result["vmt_total"], v_ref, atol=1e-3)
    assert np.allclose(result["vmt_per_capita"], vpc_ref, atol=1e-3)
    assert np.allclose(result["avg_trip_length_mi"], tl_ref, atol=1e-3)


# ══════════════════════════════════════════════════════════════════════
#  Transport GHG
# ══════════════════════════════════════════════════════════════════════


@pytest.mark.slow
def test_transport_ghg_parity() -> None:
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
        vars_={"scenario_id": "test_tghg"},
    )

    assert np.allclose(result["co2e_total_kg"], co2e_ref, atol=1e-3)
    assert np.allclose(result["co2e_per_capita_kg"], pc_ref, atol=1e-3)
