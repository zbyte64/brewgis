"""Property-based tests for dbt SQL reference formulas.  No database needed."""
# ruff: noqa: ANN201
# mypy: ignore-errors

from __future__ import annotations

import numpy as np
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tests.dbt_math.reference import (
    compute_agriculture,
    compute_building_water_ghg,
    compute_energy_demand,
    compute_impervious_surface,
    compute_internal_capture,
    compute_physical_activity,
    compute_property_tax,
    compute_service_costs,
    compute_transport_ghg,
    compute_trip_generation,
    compute_vmt,
    compute_water_demand,
)

_N_HYPOTHESIS = settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])


# ── Helpers ─────────────────────────────────────────────────────────

def _fa(n, lo=0.0, hi=1e6):
    return st.lists(st.floats(lo, hi, allow_nan=False), min_size=n, max_size=n).map(
        lambda l: np.array(l, dtype=float)
    )


# ── Composite strategies (same-length arrays) ──────────────────────

def _n(draw):
    return draw(st.integers(min_value=1, max_value=20))


@st.composite
def _pair(draw, lo1=0.0, hi1=1e6, lo2=0.0, hi2=1e6):
    n = draw(st.integers(min_value=1, max_value=20))
    return (draw(_fa(n, lo1, hi1)), draw(_fa(n, lo2, hi2)))


@st.composite
def _triple(draw, lo1=0.0, hi1=1e6, lo2=0.0, hi2=1e6, lo3=0.0, hi3=1e6):
    n = draw(st.integers(min_value=1, max_value=20))
    return (draw(_fa(n, lo1, hi1)), draw(_fa(n, lo2, hi2)), draw(_fa(n, lo3, hi3)))


@st.composite
def _quint(draw, lo1=0.0, hi1=1e6, lo2=0.0, hi2=1e6, lo3=0.0, hi3=1e6,
           lo4=0.0, hi4=1e6, lo5=0.0, hi5=1e6):
    n = draw(st.integers(min_value=1, max_value=20))
    return (draw(_fa(n, lo1, hi1)), draw(_fa(n, lo2, hi2)),
            draw(_fa(n, lo3, hi3)), draw(_fa(n, lo4, hi4)),
            draw(_fa(n, lo5, hi5)))


@st.composite
def _wdata(draw):
    n = draw(st.integers(min_value=1, max_value=10))
    return (draw(_fa(n, 0, 5000)), draw(_fa(n, 0, 10)), draw(_fa(n, 0, 500)),
            draw(_fa(n, 0, 10000)), draw(_fa(n, 0, 1e6)), draw(_fa(n, 0, 1e6)),
            draw(_fa(n, 0, 500)), draw(_fa(n, 0, 15000)))


@st.composite
def _ghg_data(draw):
    n = draw(st.integers(min_value=1, max_value=10))
    return (draw(_fa(n, 0, 1e7)), draw(_fa(n, 0, 1e7)),
            draw(_fa(n, 0, 1e7)), draw(_fa(n, 0, 1e7)),
            draw(_fa(n, 0, 1e9)), draw(_fa(n, 0, 15000)))


@st.composite
def _ic_data(draw):
    n = draw(st.integers(min_value=1, max_value=10))
    return (draw(_fa(n, 0, 50000)), draw(_fa(n, 0, 50000)),
            draw(_fa(n, 0, 50000)), draw(st.floats(0.0, 1.0)),
            draw(_fa(n, 0, 100)), draw(st.floats(min_value=1e-6, max_value=1e6)))


# ══════════════════════════════════════════════════════════════════════
#  Fiscal — Property Tax
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.slow
@given(_pair(0, 5000, 0, 5e6))
@_N_HYPOTHESIS
def test_property_tax_all_non_negative(pair):
    du, bsqt = pair
    av_res, av_nonres, revenue = compute_property_tax(du, bsqt)
    assert np.all(av_res >= 0)
    assert np.all(av_nonres >= 0)
    assert np.all(revenue >= 0)


@pytest.mark.slow
@given(_pair(0, 5000, 0, 5e6))
@_N_HYPOTHESIS
def test_property_tax_zero_inputs(pair):
    du, bsqt = pair
    av_res, _, _ = compute_property_tax(np.zeros_like(du), bsqt)
    assert np.all(av_res == 0)
    _, av_nonres, _ = compute_property_tax(du, np.zeros_like(bsqt))
    assert np.all(av_nonres == 0)


# ══════════════════════════════════════════════════════════════════════
#  Fiscal — Service Costs
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.slow
@given(_triple(0, 5000, 0, 15000, 0, 10000))
@_N_HYPOTHESIS
def test_service_costs_total_identity(triple):
    du, pop, emp = triple
    schools, safety, roads, total = compute_service_costs(du, pop, emp)
    assert np.all(total >= 0)
    assert np.allclose(total, schools + safety + roads)


# ══════════════════════════════════════════════════════════════════════
#  Land Consumption — Impervious Surface
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.slow
@given(_quint(0, 5e6, 0, 5000, 0, 10000, 0, 100, 0, 100))
@_N_HYPOTHESIS
def test_impervious_surface(quint):
    bsqt, du, emp, gross_acres, dev_acres = quint
    imp_sqft, imp_acres, pervious, imp_pct = compute_impervious_surface(
        bsqt, du, emp, gross_acres, dev_acres,
    )
    assert np.all(imp_sqft >= 0)
    assert np.all(imp_acres >= 0)
    assert np.all(pervious >= 0)
    assert np.all(imp_pct >= 0)
    # Unit conversion: impervious_acres * 43560 ≈ impervious_sqft
    assert np.allclose(imp_acres * 43560.0, imp_sqft, atol=1e-3)


# ══════════════════════════════════════════════════════════════════════
#  VMT
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.slow
@given(_triple(0, 50000, 0, 100, 0, 15000))
@_N_HYPOTHESIS
def test_vmt_formulas(triple):
    auto, length, pop = triple
    vmt, vmt_pc, trip_mi, _ = compute_vmt(auto, length, pop)
    assert np.all(vmt >= 0)
    assert np.all(vmt_pc >= 0)
    assert np.all(trip_mi >= 0)
    assert np.allclose(trip_mi, length * 0.621371, atol=1e-6)
    mask = pop > 0
    if np.any(mask):
        assert np.allclose(vmt[mask] / pop[mask], vmt_pc[mask], atol=1e-6)


# ══════════════════════════════════════════════════════════════════════
#  Transport GHG
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.slow
@given(_pair(0, 1e6, 0, 15000))
@_N_HYPOTHESIS
def test_transport_ghg_formulas(pair):
    vmt, pop = pair
    co2e, co2e_pc = compute_transport_ghg(vmt, pop)
    assert np.all(co2e >= 0)
    assert np.all(co2e_pc >= 0)
    assert np.allclose(co2e, vmt * 0.411, atol=1e-6)
    co2e_adj, _ = compute_transport_ghg(vmt, pop, speed_adjust=True)
    assert np.allclose(co2e_adj, co2e * 1.15, atol=1e-6)
    mask = pop > 0
    if np.any(mask):
        assert np.allclose(co2e[mask] / pop[mask], co2e_pc[mask], atol=1e-6)


# ══════════════════════════════════════════════════════════════════════
#  Physical Activity
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.slow
@given(_quint(0, 50000, 0, 50000, 0, 100, 0, 50000, 0, 50000))
@_N_HYPOTHESIS
def test_physical_activity_met_hours(quint):
    walk, bike, length, auto, transit = quint
    wmh, bmh, total, *_, share = compute_physical_activity(
        walk, bike, length, auto, transit,
    )
    assert np.all(wmh >= 0)
    assert np.all(bmh >= 0)
    assert np.all(total >= 0)
    assert np.all(share >= 0)
    assert np.all(share <= 1.0 + 1e-10)
    assert np.allclose(total, wmh + bmh, atol=1e-6)


# ══════════════════════════════════════════════════════════════════════
#  Energy Demand
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.slow
@given(_quint(0, 5000, 0, 5e6, 0, 100, 0, 500, 0, 500))
@_N_HYPOTHESIS
def test_energy_demand_sum_and_intensity(quint):
    du, bsqt, acres_dev, elec_eui, gas_eui = quint
    er, gr, enr, gnr, total, intensity = compute_energy_demand(
        du, bsqt, acres_dev, elec_eui, gas_eui,
    )
    assert np.all(total >= 0)
    assert np.allclose(total, er + gr + enr + gnr, atol=1e-6)
    assert np.all(intensity >= 0)
    mask = bsqt > 0
    if np.any(mask):
        assert np.allclose(intensity[mask], total[mask] / bsqt[mask], atol=1e-6)


# ══════════════════════════════════════════════════════════════════════
#  Water Demand
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.slow
@given(_wdata())
@_N_HYPOTHESIS
def test_water_demand_total_identity(data):
    hh, hh_size, indoor_rate, emp, res_irr, com_irr, outdoor_rate, pop = data
    ri, ro, ni, no, total, per_unit = compute_water_demand(
        hh, hh_size, indoor_rate, emp, res_irr, com_irr, outdoor_rate, pop,
    )
    assert np.all(total >= 0)
    assert np.allclose(total, ri + ro + ni + no, atol=1e-3)
    assert np.all(per_unit >= 0)


# ══════════════════════════════════════════════════════════════════════
#  Building & Water GHG
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.slow
@given(_ghg_data())
@_N_HYPOTHESIS
def test_building_water_ghg_identity(data):
    e_res, e_nonres, g_res, g_nonres, w_total, pop = data
    co2e_en, co2e_w, co2e_total, co2e_pc = compute_building_water_ghg(
        e_res, e_nonres, g_res, g_nonres, w_total, pop,
    )
    assert np.all(co2e_total >= 0)
    assert np.allclose(co2e_total, co2e_en + co2e_w, atol=1e-3)
    assert np.all(co2e_pc >= 0)
    mask = pop > 0
    if np.any(mask):
        assert np.allclose(co2e_total[mask] / pop[mask], co2e_pc[mask], atol=1e-3)


# ══════════════════════════════════════════════════════════════════════
#  Agriculture
# ══════════════════════════════════════════════════════════════════════

@st.composite
def _ag_data(draw):
    n = draw(st.integers(min_value=1, max_value=10))
    ag = draw(_fa(n, 0, 100))
    dev = draw(_fa(n, 0, 100))
    rural = draw(_fa(n, 0, 1).map(lambda a: a > 0.5))
    return ag, dev, rural


@pytest.mark.slow
@given(_ag_data())
@_N_HYPOTHESIS
def test_agriculture_net_return_formula(data):
    ag_acres, dev_acres, is_rural = data
    (cultivated, yield_tons, market, cost, net,
     water_af, labor, trucks) = compute_agriculture(ag_acres, dev_acres, is_rural)
    assert np.all(cultivated >= 0)
    assert np.all(yield_tons >= 0)
    assert np.all(market >= 0)
    assert np.all(cost >= 0)
    assert np.allclose(net, market - cost, atol=1e-6)
    assert np.all(water_af >= 0)
    assert np.all(labor >= 0)
    assert np.all(trucks >= 0)


# ══════════════════════════════════════════════════════════════════════
#  Trip Generation
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.slow
@given(_quint(0, 5000, 0, 5e6, 0, 50, 0, 1, 0, 0))
@_N_HYPOTHESIS
def test_trip_generation_purpose_split(quint):
    du, bsqt, override, pass_by, _ = quint
    res, nonres, total, hbw, hbo, nhb = compute_trip_generation(
        du, bsqt, override, pass_by,
    )
    assert np.all(res >= 0)
    assert np.all(nonres >= 0)
    assert np.all(total >= 0)
    assert np.all(hbw >= 0) and np.all(hbo >= 0) and np.all(nhb >= 0)
    assert np.allclose(hbw + hbo + nhb, total, atol=1e-6)


# ══════════════════════════════════════════════════════════════════════
#  Internal Capture
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.slow
@given(_ic_data())
@_N_HYPOTHESIS
def test_internal_capture_bounds(data):
    outbound, inbound, intra, frac, length, radius = data
    internal, capture, external = compute_internal_capture(
        outbound, inbound, intra, frac, length, radius,
    )
    assert np.all(capture >= 0)
    assert np.all(capture <= 1.0 + 1e-10)
    assert np.all(internal >= 0)
    assert np.all(external >= 0)


# ══════════════════════════════════════════════════════════════════════
#  Edge cases — empty input
# ══════════════════════════════════════════════════════════════════════

def test_all_refs_handle_empty_input():
    e = np.array([], dtype=float)
    cases = [
        ("property_tax", lambda: compute_property_tax(e, e)),
        ("service_costs", lambda: compute_service_costs(e, e, e)),
        ("vmt", lambda: compute_vmt(e, e, e)),
        ("transport_ghg", lambda: compute_transport_ghg(e, e)),
        ("impervious", lambda: compute_impervious_surface(e, e, e, e, e)),
        ("physical_activity", lambda: compute_physical_activity(e, e, e, e, e)),
        ("energy_demand", lambda: compute_energy_demand(e, e, e, e, e)),
        ("water_demand", lambda: compute_water_demand(e, e, e, e, e, e, e, e)),
        ("building_ghg", lambda: compute_building_water_ghg(e, e, e, e, e, e)),
        ("agriculture", lambda: compute_agriculture(e, e, e)),
        ("trip_generation", lambda: compute_trip_generation(e, e, e, e)),
    ]
    for name, fn in cases:
        result = fn()
        for arr in result if isinstance(result, tuple) else [result]:
            assert len(arr) == 0, f"{name}: expected empty array"
