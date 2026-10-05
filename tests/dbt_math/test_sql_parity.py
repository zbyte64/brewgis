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

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from tests.dbt_math.reference import compute_agriculture
from tests.dbt_math.reference import compute_building_water_ghg
from tests.dbt_math.reference import compute_energy_demand
from tests.dbt_math.reference import compute_impervious_surface
from tests.dbt_math.reference import compute_mode_choice
from tests.dbt_math.reference import compute_physical_activity
from tests.dbt_math.reference import compute_property_tax
from tests.dbt_math.reference import compute_service_costs
from tests.dbt_math.reference import compute_transport_ghg
from tests.dbt_math.reference import compute_trip_generation
from tests.dbt_math.reference import compute_vmt
from tests.dbt_math.reference import compute_water_demand
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
    building_sqft_residential: np.ndarray | None = None,
    building_sqft_commercial: np.ndarray | None = None,
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
        "building_sqft_residential": (
            building_sqft_residential
            if building_sqft_residential is not None
            else np.full(n, 1e4)
        ),
        "building_sqft_commercial": (
            building_sqft_commercial
            if building_sqft_commercial is not None
            else np.full(n, 1e4)
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

    es_df = _core_es_df(pid, du=du, building_sqft_commercial=bsqt)
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


# ══════════════════════════════════════════════════════════════════════
#  Land consumption — Impervious Surface
# ══════════════════════════════════════════════════════════════════════


@pytest.mark.slow
def test_land_consumption_parity(parity_scenario: str) -> None:
    """``land_consumption``'s impervious-surface columns match the reference.

    The reference carries the module's parameter defaults (ground coverage,
    parking per unit / per employee, parking space size, row fraction), which
    are what a run with no scenario overrides renders.
    """
    du = np.array([0.0, 5.0, 100.0, 2.5])
    bsqt = np.array([0.0, 2000.0, 50000.0, 100.0])
    emp = np.array([0.0, 3.0, 50.0, 1.0])
    gross = np.array([1.0, 2.0, 5.0, 0.5])
    dev = np.array([0.0, 1.0, 4.0, 0.25])
    pid = np.arange(len(du), dtype=int)

    imp_sqft, imp_acres, pervious, imp_pct = compute_impervious_surface(
        bsqt, du, emp, gross, dev
    )

    es_df = _core_es_df(
        pid,
        du=du,
        emp=emp,
        building_sqft_total=bsqt,
        area_gross_acres=gross,
        acres_developed=dev,
        built_form_id=np.array([None, "bf a", "bf b", "bf c"], dtype=object),
        parcel_acres_developed=dev,
        parcel_acres_agriculture=np.zeros(len(pid)),
        parcel_acres_open_space=np.zeros(len(pid)),
        parcel_acres_vacant=gross,
    )
    result = run_model(
        "land_consumption",
        upstream={"core_end_state": es_df},
        scenario_schema=parity_scenario,
    ).sort_values("parcel_id")

    assert np.allclose(result["impervious_sqft"], imp_sqft, atol=1e-3)
    assert np.allclose(result["impervious_acres"], imp_acres, atol=1e-9)
    assert np.allclose(result["pervious_acres"], pervious, atol=1e-9)
    assert np.allclose(result["impervious_pct"], imp_pct, atol=1e-9)


# ══════════════════════════════════════════════════════════════════════
#  Physical Activity
# ══════════════════════════════════════════════════════════════════════


@pytest.mark.slow
def test_physical_activity_parity(parity_scenario: str) -> None:
    """``physical_activity`` MET-hours match the reference.

    Each active mode uses its own mean trip length and speed (the parameter
    defaults), never the region's vehicle trip length.
    """
    walk = np.array([0.0, 40.0, 250.0])
    bike = np.array([0.0, 12.0, 60.0])
    auto = np.array([0.0, 300.0, 1200.0])
    transit = np.array([0.0, 25.0, 90.0])
    pid = np.arange(len(walk), dtype=int)

    ref = compute_physical_activity(walk, bike, 0.8, 3.2, auto, transit)

    mc_df = pd.DataFrame(
        {
            "parcel_id": pid,
            "trips_walk": walk,
            "trips_bike": bike,
            "trips_auto": auto,
            "trips_transit": transit,
        }
    )
    es_df = _core_es_df(pid)

    result = run_model(
        "physical_activity",
        upstream={"mode_choice": mc_df, "core_end_state": es_df},
        scenario_schema=parity_scenario,
    ).sort_values("parcel_id")

    for column, expected in zip(
        ("walk_met_hours", "bike_met_hours", "total_met_hours", "active_trip_share"),
        (ref[0], ref[1], ref[2], ref[5]),
        strict=True,
    ):
        assert np.allclose(result[column], expected, atol=1e-9), column


# ══════════════════════════════════════════════════════════════════════
#  Water Demand
# ══════════════════════════════════════════════════════════════════════


@pytest.mark.slow
def test_water_demand_parity(parity_scenario: str) -> None:
    """``water_demand`` L/yr by category matches the reference.

    One parcel is in an ETo zone (outdoor at the ETo depth), one has no zone
    (NULL depth → the built form's flat outdoor rate), which is the COALESCE
    branch the reference's NaN sentinel reproduces.
    """
    pop = np.array([0.0, 250.0, 40.0])
    indoor = np.array([200.0, 180.0, 210.0])
    emp = np.array([0.0, 50.0, 5.0])
    res_irr = np.array([0.0, 0.5, 0.1])
    com_irr = np.array([0.0, 0.2, 0.0])
    eto = np.array([np.nan, 1449.0, 900.0])
    flat_outdoor = np.array([100.0, 95.0, 105.0])
    pid = np.arange(len(pop), dtype=int)

    ref = compute_water_demand(pop, indoor, emp, res_irr, com_irr, eto, flat_outdoor)

    es_df = _core_es_df(
        pid,
        pop=pop,
        emp=emp,
        du=np.array([0.0, 100.0, 16.0]),
        acres_developed=np.array([0.0, 1.0, 0.2]),
        indoor_water_rate=indoor,
        residential_irrigated_area=res_irr,
        commercial_irrigated_area=com_irr,
        annual_eto_mm=eto,
        outdoor_water_rate=flat_outdoor,
    )
    result = run_model(
        "water_demand",
        upstream={"core_end_state": es_df},
        scenario_schema=parity_scenario,
    ).sort_values("parcel_id")

    for column, expected in zip(
        (
            "water_demand_res_indoor",
            "water_demand_res_outdoor",
            "water_demand_nonres_indoor",
            "water_demand_nonres_outdoor",
            "water_demand_total",
            "water_demand_per_unit",
        ),
        ref,
        strict=True,
    ):
        assert np.allclose(result[column], expected, atol=1e-6), column


# ══════════════════════════════════════════════════════════════════════
#  Building & Water GHG
# ══════════════════════════════════════════════════════════════════════


@pytest.mark.slow
def test_building_water_ghg_parity(parity_scenario: str) -> None:
    """``building_water_ghg`` CO2e matches the reference.

    Energy and water are read from their models' outputs; the reference carries
    the parameter defaults for the eGRID, gas, and water/wastewater factors.
    """
    e_res = np.array([0.0, 12000.0, 4000.0])
    e_nonres = np.array([0.0, 5000.0, 1500.0])
    g_res = np.array([0.0, 9000.0, 3000.0])
    g_nonres = np.array([0.0, 2000.0, 800.0])
    w_total = np.array([0.0, 2.5e6, 4.0e5])
    pop = np.array([0.0, 250.0, 40.0])
    pid = np.arange(len(pop), dtype=int)

    ref = compute_building_water_ghg(e_res, e_nonres, g_res, g_nonres, w_total, pop)

    ed_df = pd.DataFrame(
        {
            "parcel_id": pid,
            "energy_electricity_res": e_res,
            "energy_gas_res": g_res,
            "energy_electricity_nonres": e_nonres,
            "energy_gas_nonres": g_nonres,
        }
    )
    wd_df = pd.DataFrame({"parcel_id": pid, "water_demand_total": w_total})
    es_df = _core_es_df(pid, pop=pop)

    result = run_model(
        "building_water_ghg",
        upstream={
            "energy_demand": ed_df,
            "water_demand": wd_df,
            "core_end_state": es_df,
        },
        scenario_schema=parity_scenario,
    ).sort_values("parcel_id")

    for column, expected in zip(
        (
            "co2e_energy_total_kg",
            "co2e_water_total_kg",
            "co2e_total_kg",
            "co2e_per_capita_kg",
        ),
        ref,
        strict=True,
    ):
        assert np.allclose(result[column], expected, atol=1e-3, rtol=1e-9), column


# ══════════════════════════════════════════════════════════════════════
#  Agriculture
# ══════════════════════════════════════════════════════════════════════


@pytest.mark.slow
def test_agriculture_parity(parity_scenario: str) -> None:
    """``agriculture`` production and resource columns match the reference.

    Every parcel qualifies (agricultural acres, or developed rural acres), so
    the model's WHERE keeps them all and the rows line up with the reference.
    """
    ag = np.array([5.0, 50.0, 0.0, 10.0])
    dev = np.array([0.0, 0.0, 30.0, 5.0])
    rural = np.array([False, False, True, False])
    pid = np.arange(len(ag), dtype=int)

    ref = compute_agriculture(ag, dev, rural)

    es_df = _core_es_df(
        pid,
        parcel_acres_agriculture=ag,
        acres_developed=dev,
        land_development_category=np.where(rural, "rural", "urban"),
    )
    result = run_model(
        "agriculture",
        upstream={"core_end_state": es_df},
        scenario_schema=parity_scenario,
    ).sort_values("parcel_id")

    for column, expected in zip(
        (
            "acres_cultivated",
            "crop_yield_tons",
            "market_value",
            "production_cost",
            "net_return",
            "water_consumption_af",
            "labor_hours",
            "truck_trips",
        ),
        ref,
        strict=True,
    ):
        assert np.allclose(result[column], expected, atol=1e-6), column


# ══════════════════════════════════════════════════════════════════════
#  Energy Demand
# ══════════════════════════════════════════════════════════════════════

_ZONE = 7
"""The CEC Building Climate Zone the synthetic baselines cover."""

_RES_DU_TYPES = ("detsf_ll", "detsf_sl", "attsf", "mf")
_RES_ELEC = np.array([7000.0, 6000.0, 5000.0, 4000.0])
_RES_GAS = np.array([1000.0, 900.0, 800.0, 700.0])

_COM_USES = (
    "retail_services",
    "restaurant",
    "accommodation",
    "arts_entertainment",
    "other_services",
    "office_services",
    "public_admin",
    "education",
    "medical_services",
    "transport_warehousing",
    "wholesale",
)
_COM_ELEC = np.array([14.0 + i for i in range(len(_COM_USES))])
_COM_GAS = np.array([0.09 + i * 0.01 for i in range(len(_COM_USES))])


def _zone_rates(rates: np.ndarray, zones: np.ndarray) -> np.ndarray:
    """One rate row per parcel: the zone's rates, or NaN where the zone is not covered."""
    return np.array(
        [rates if zone == _ZONE else np.full(len(rates), np.nan) for zone in zones]
    )


@pytest.mark.slow
def test_energy_demand_parity(parity_scenario: str) -> None:
    """``energy_demand`` kWh/yr matches the reference.

    Three branches: a parcel in a covered zone uses the zone's per-class
    intensities, one with no zone and one in an uncovered zone fall back to the
    built form's flat EUI, and a covered parcel with no dwelling units or area
    keeps the zone branch's zero.
    """
    # 0 in-zone with dwelling units + retail area; 1 no zone; 2 uncovered zone;
    # 3 in-zone but empty.
    zones = np.array([_ZONE, np.nan, 99.0, _ZONE])
    du_ll = np.array([10.0, 5.0, 0.0, 0.0])
    du_sl = np.array([0.0, 0.0, 0.0, 0.0])
    du_attsf = np.array([0.0, 0.0, 0.0, 0.0])
    du_mf2to4 = np.array([0.0, 0.0, 4.0, 0.0])
    du_mf5p = np.array([0.0, 0.0, 6.0, 0.0])
    res_sqft = np.array([5000.0, 2000.0, 1000.0, 0.0])
    com_sqft = np.array([50.0, 300.0, 200.0, 0.0])
    elec_eui = np.array([100.0, 100.0, 80.0, 100.0])
    gas_eui = np.array([50.0, 50.0, 40.0, 50.0])
    pid = np.arange(4, dtype=int)

    # Every commercial use type present for use 0 only.
    com_areas = {use: np.zeros(4) for use in _COM_USES}
    com_areas["retail_services"][0] = 1000.0

    du_matrix = np.column_stack([du_ll, du_sl, du_attsf, du_mf2to4 + du_mf5p])
    com_area_matrix = np.column_stack([com_areas[use] for use in _COM_USES])

    ref = compute_energy_demand(
        du_matrix,
        _zone_rates(_RES_ELEC, zones),
        _zone_rates(_RES_GAS, zones),
        com_area_matrix,
        _zone_rates(_COM_ELEC, zones),
        _zone_rates(_COM_GAS, zones),
        res_sqft,
        com_sqft,
        elec_eui,
        gas_eui,
    )

    residential_seed = pd.DataFrame(
        {
            "zone": np.full(len(_RES_DU_TYPES), _ZONE),
            "du_type": np.array(_RES_DU_TYPES, dtype=object),
            "elec_kwh_per_du_yr": _RES_ELEC,
            "gas_therm_per_du_yr": _RES_GAS,
        }
    )
    commercial_seed = pd.DataFrame(
        {
            "zone": np.full(len(_COM_USES), _ZONE),
            "use_type": np.array(_COM_USES, dtype=object),
            "elec_kwh_per_sqft_yr": _COM_ELEC,
            "gas_therm_per_sqft_yr": _COM_GAS,
        }
    )

    es_df = _core_es_df(
        pid,
        du=du_ll + du_sl + du_attsf + du_mf2to4 + du_mf5p,
        acres_developed=np.zeros(4),
        building_sqft_total=res_sqft + com_sqft,
        building_sqft_residential=res_sqft,
        building_sqft_commercial=com_sqft,
        du_detsf_ll=du_ll,
        du_detsf_sl=du_sl,
        du_attsf=du_attsf,
        du_mf2to4=du_mf2to4,
        du_mf5p=du_mf5p,
        electricity_eui=elec_eui,
        gas_eui=gas_eui,
        title24_zone=zones,
        **{f"bldg_area_{use}": com_areas[use] for use in _COM_USES},
    )

    result = run_model(
        "energy_demand",
        upstream={"core_end_state": es_df},
        seeds={
            "residential_energy_baseline": residential_seed,
            "commercial_energy_baseline": commercial_seed,
        },
        scenario_schema=parity_scenario,
    ).sort_values("parcel_id")

    for column, expected in zip(
        (
            "energy_electricity_res",
            "energy_gas_res",
            "energy_electricity_nonres",
            "energy_gas_nonres",
            "energy_total",
            "energy_intensity_kwh_per_sqft",
        ),
        ref,
        strict=True,
    ):
        assert np.allclose(result[column], expected, atol=1e-6), column
