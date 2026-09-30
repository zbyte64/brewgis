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

import json

import numpy as np
import pandas as pd
import pytest

from tests.dbt_math.reference import compute_mode_choice
from tests.dbt_math.reference import compute_property_tax
from tests.dbt_math.reference import compute_service_costs
from tests.dbt_math.reference import compute_transport_ghg
from tests.dbt_math.reference import compute_trip_generation
from tests.dbt_math.reference import compute_vmt
from tests.dbt_math.sqlmesh_model_runner import run_model

pytestmark = [
    pytest.mark.integration,
    # transaction=True so the `parity_scenario` fixture's committed rows are
    # visible to SQLMesh's forked model-loading workers, and flushed after.
    pytest.mark.django_db(transaction=True),
]

# transport_vehicles_per_capita's default (module_registry.ANALYSIS_PARAMETERS):
# what a run with no scenario overrides renders, and therefore what the parity
# reference has to be handed. The drift guard for it and the reference's bike
# coefficients is tests/workspace/test_module_registry.py.
_VEHICLES_PER_CAPITA = 0.8


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
    # Purpose trips, the end-state attributes the D-variables read, and the
    # quarter-mile / one-mile context. Parcel 0 has no trips at all, which is
    # the zero-denominator case (its shares are NULL, its trip counts zero).
    trips_hbw = np.array([0.0, 30.0, 80.0, 12.0], dtype=float)
    trips_hbo = np.array([0.0, 70.0, 175.0, 28.0], dtype=float)
    trips_nhb = np.array([0.0, 40.0, 100.0, 16.0], dtype=float)
    area = np.array([1.0, 0.5, 4.0, 2.0], dtype=float)
    intersection_density = np.array([0.0, 5.0, 30.0, 2.0], dtype=float)
    pop = np.array([0.0, 60.0, 250.0, 40.0], dtype=float)
    hh = np.array([0.0, 25.0, 100.0, 16.0], dtype=float)
    emp = np.array([0.0, 4.0, 40.0, 2.0], dtype=float)
    # NULL on two parcels: the model then falls back to the built form's
    # household size (or 2.577).
    household_size = np.array([np.nan, 2.4, np.nan, 2.6], dtype=float)
    qmb_pop = np.array([0.0, 800.0, 4000.0, 300.0], dtype=float)
    qmb_emp = np.array([0.0, 200.0, 1500.0, 50.0], dtype=float)
    qmb_res_acres = np.array([0.0, 40.0, 100.0, 20.0], dtype=float)
    qmb_emp_acres = np.array([0.0, 10.0, 30.0, 5.0], dtype=float)
    qmb_mixed_acres = np.array([0.0, 5.0, 12.0, 2.0], dtype=float)
    emp_1mile = np.array([0.0, 900.0, 6000.0, 250.0], dtype=float)
    pid = np.arange(len(trips_hbw), dtype=int)

    reference = compute_mode_choice(
        trips_hbw,
        trips_hbo,
        trips_nhb,
        area,
        intersection_density,
        pop,
        hh,
        emp,
        household_size,
        qmb_pop,
        qmb_emp,
        qmb_res_acres,
        qmb_emp_acres,
        qmb_mixed_acres,
        emp_1mile,
        # transport_vehicles_per_capita's default, which is what a run with no
        # scenario overrides renders.
        _VEHICLES_PER_CAPITA,
    )

    tg_df = pd.DataFrame(
        {
            "parcel_id": pid,
            "trips_hbw": trips_hbw,
            "trips_hbo": trips_hbo,
            "trips_nhb": trips_nhb,
        }
    )
    es_df = _core_es_df(
        pid,
        area_gross_acres=area,
        intersection_density=intersection_density,
        pop=pop,
        emp=emp,
        hh=hh,
        household_size=household_size,
    )
    qm_df = pd.DataFrame(
        {
            "parcel_id": pid,
            "qmb_pop": qmb_pop,
            "qmb_emp": qmb_emp,
            "qmb_res_acres": qmb_res_acres,
            "qmb_emp_acres": qmb_emp_acres,
            "qmb_mixed_acres": qmb_mixed_acres,
            "emp_1mile": emp_1mile,
        }
    )

    result = run_model(
        "mode_choice",
        upstream={
            "trip_generation": tg_df,
            "core_end_state": es_df,
            "quarter_mile_context": qm_df,
        },
        scenario_schema=parity_scenario,
    )

    columns = (
        "trips_auto",
        "trips_transit",
        "trips_walk",
        "trips_bike",
        "trips_internal_capture",
        "mode_share_auto",
        "mode_share_transit",
        "mode_share_walk",
        "mode_share_bike",
        "mode_share_internal_capture",
    )
    for column, expected in zip(columns, reference, strict=True):
        assert np.allclose(result[column], expected, atol=1e-8, equal_nan=True), column


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

    # VMT reads the mode-choice auto trips and the ``trip_lengths`` model — the
    # region's reference zone length where it has one, else the scaled gravity
    # length — not ``trip_distribution``'s own gravity length.
    mc_df = pd.DataFrame({"parcel_id": pid, "trips_auto": auto_trips})
    tl_df = pd.DataFrame({"parcel_id": pid, "avg_trip_length_km": avg_trip_length_km})
    # vmt reads ``es.hh`` for its per-household columns.
    es_df = _core_es_df(pid, pop=pop, hh=np.full(len(pid), 40.0))

    result = run_model(
        "vmt",
        upstream={
            "mode_choice": mc_df,
            "trip_lengths": tl_df,
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

    co2e_ref, co2e_annual_ref, pc_ref = compute_transport_ghg(vmt, pop)

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
    assert np.allclose(result["co2e_annual_kg"], co2e_annual_ref, atol=1e-3)
    assert np.allclose(result["co2e_per_capita_kg"], pc_ref, atol=1e-3)


# ══════════════════════════════════════════════════════════════════════
#  Trip Generation
# ══════════════════════════════════════════════════════════════════════


@pytest.mark.slow
def test_trip_generation_parity(parity_scenario: str) -> None:
    """SQLMesh trip_generation output matches the Python reference.

    Every employment bucket is exercised, one row carries jobs but no sector
    mix (the retail fallback), and one is mixed-use — dwelling units AND jobs.
    A model that picked "residential" or "non-residential" per parcel from a
    density being non-zero, or that priced anything by floor area, would
    disagree with the reference on this input.
    """
    pid = np.arange(8, dtype=int)
    du_detsf_ll = np.array([10.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 5.0])
    du_detsf_sl = np.array([4.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    du_attsf = np.array([0.0, 7.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    du_mf2to4 = np.array([0.0, 12.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    du_mf5p = np.array([0.0, 0.0, 20.0, 0.0, 0.0, 60.0, 0.0, 0.0])
    emp = np.array([0.0, 0.0, 0.0, 100.0, 25.0, 80.0, 0.0, 50.0])
    # Percent shares of emp_per_acre as the built forms table carries them; row
    # 3 leaves a residual for sectors SACOG does not publish, which both sides
    # have to normalize, and row 4 declares no mix at all.
    shares = [
        {},
        {},
        {},
        {"retail_services": 60.0, "office_services": 20.0, "arts_entertainment": 10.0},
        {},
        {"restaurant": 40.0, "public_admin": 30.0},
        {},
        {"manufacturing": 70.0, "education": 30.0},
    ]
    reference = compute_trip_generation(
        du_detsf_ll + du_detsf_sl,
        du_mf2to4,
        du_mf5p,
        du_attsf,
        emp,
        shares,
    )

    es_df = _core_es_df(
        pid,
        du=du_detsf_ll + du_detsf_sl + du_mf2to4 + du_mf5p,
        emp=emp,
        du_detsf_ll=du_detsf_ll,
        du_detsf_sl=du_detsf_sl,
        du_attsf=du_attsf,
        du_mf2to4=du_mf2to4,
        du_mf5p=du_mf5p,
        # The model's du_type audit reads these two off core_end_state: every
        # parcel holding dwelling units has to name a housing class.
        du_type=np.array(
            [
                "detsf_ll",
                "mf2to4",
                "mf5p",
                "",
                "",
                "mf5p",
                "",
                "detsf_sl",
            ],
            dtype=object,
        ),
        built_form_key=np.array([f"bf {i}" for i in pid], dtype=object),
        jobs_by_sector=np.array([json.dumps(s) for s in shares], dtype=object),
    )

    result = run_model(
        "trip_generation",
        upstream={"core_end_state": es_df},
        scenario_schema=parity_scenario,
    )

    columns = (
        "trips_res",
        "trips_school",
        "trips_nonres",
        "trips_total",
        "trips_hbw",
        "trips_hbo",
        "trips_nhb",
    )
    for column, expected in zip(columns, reference, strict=True):
        assert np.allclose(result[column], expected, atol=1e-6), column
