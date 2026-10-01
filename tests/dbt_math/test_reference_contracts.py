"""Property-based tests for dbt SQL reference formulas.  No database needed."""
# ruff: noqa: ANN201
# mypy: ignore-errors

from __future__ import annotations

import numpy as np
import pytest
from hypothesis import HealthCheck
from hypothesis import given
from hypothesis import settings
from hypothesis import strategies as st

from tests.dbt_math.reference import compute_agriculture
from tests.dbt_math.reference import compute_building_water_ghg
from tests.dbt_math.reference import compute_energy_demand
from tests.dbt_math.reference import compute_impervious_surface
from tests.dbt_math.reference import compute_internal_capture
from tests.dbt_math.reference import compute_mode_choice
from tests.dbt_math.reference import compute_physical_activity
from tests.dbt_math.reference import compute_property_tax
from tests.dbt_math.reference import compute_service_costs
from tests.dbt_math.reference import compute_transport_ghg
from tests.dbt_math.reference import compute_trip_generation
from tests.dbt_math.reference import compute_vmt
from tests.dbt_math.reference import compute_water_demand

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
def _quint(
    draw,
    lo1=0.0,
    hi1=1e6,
    lo2=0.0,
    hi2=1e6,
    lo3=0.0,
    hi3=1e6,
    lo4=0.0,
    hi4=1e6,
    lo5=0.0,
    hi5=1e6,
):
    n = draw(st.integers(min_value=1, max_value=20))
    return (
        draw(_fa(n, lo1, hi1)),
        draw(_fa(n, lo2, hi2)),
        draw(_fa(n, lo3, hi3)),
        draw(_fa(n, lo4, hi4)),
        draw(_fa(n, lo5, hi5)),
    )


@st.composite
def _wdata(draw):
    n = draw(st.integers(min_value=1, max_value=10))
    return (
        draw(_fa(n, 0, 15000)),
        draw(_fa(n, 0, 500)),
        draw(_fa(n, 0, 10000)),
        draw(_fa(n, 0, 1e6)),
        draw(_fa(n, 0, 1e6)),
        draw(_fa(n, 0, 500)),
    )


@st.composite
def _ghg_data(draw):
    n = draw(st.integers(min_value=1, max_value=10))
    return (
        draw(_fa(n, 0, 1e7)),
        draw(_fa(n, 0, 1e7)),
        draw(_fa(n, 0, 1e7)),
        draw(_fa(n, 0, 1e7)),
        draw(_fa(n, 0, 1e9)),
        draw(_fa(n, 0, 15000)),
    )


@st.composite
def _ic_data(draw):
    n = draw(st.integers(min_value=1, max_value=10))
    return (
        draw(_fa(n, 0, 50000)),
        draw(_fa(n, 0, 50000)),
        draw(_fa(n, 0, 50000)),
        draw(st.floats(0.0, 1.0)),
        draw(_fa(n, 0, 100)),
        draw(st.floats(min_value=1e-6, max_value=1e6)),
    )


# Hypothesis explores denormals (5e-324 acres, jobs, households) at the edges of
# a range, and the reference's guarded ``ln`` turns one into a logit of about
# -700 — where the sigmoid's exponent overflows. Such a value is degenerate
# rather than a case the model claims to handle (the SQL's ``EXP`` would raise on
# it), and the ``ln`` guard needs a floor anyway for a count below 1, so the
# mode-choice draws round anything under this to zero.
_DEGENERATE_BELOW = 1e-6


def _mc_float(n, lo, hi):
    """``_fa`` for the mode-choice draws, with denormals rounded to zero."""

    def normalize(values):
        array = np.array(values, dtype=float)
        return np.where(array < _DEGENERATE_BELOW, 0.0, array)

    return st.lists(st.floats(lo, hi, allow_nan=False), min_size=n, max_size=n).map(
        normalize
    )


@st.composite
def _mc_data(draw):
    """Mode-choice inputs: purpose trips, end-state attributes, buffer context.

    Wide, deliberately: the auto residual's zero clamp is a bound the model
    itself carries, so the properties asserted on these draws hold whether or
    not it binds.
    """
    n = draw(st.integers(min_value=1, max_value=10))
    return (
        draw(_mc_float(n, 0, 50000)),
        draw(_mc_float(n, 0, 50000)),
        draw(_mc_float(n, 0, 50000)),
        draw(_mc_float(n, 0, 10)),
        draw(_mc_float(n, 0, 500)),
        draw(_mc_float(n, 0, 20000)),
        draw(_mc_float(n, 0, 2000)),
        draw(_mc_float(n, 0, 20000)),
        draw(_mc_float(n, 0, 8)),
        draw(_mc_float(n, 0, 50000)),
        draw(_mc_float(n, 0, 50000)),
        draw(_mc_float(n, 0, 2000)),
        draw(_mc_float(n, 0, 2000)),
        draw(_mc_float(n, 0, 2000)),
        draw(_mc_float(n, 0, 20000)),
    )


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
        bsqt,
        du,
        emp,
        gross_acres,
        dev_acres,
    )
    assert np.all(imp_sqft >= 0)
    assert np.all(imp_acres >= 0)
    assert np.all(pervious >= 0)
    assert np.all(imp_pct >= 0)
    # Unit conversion: impervious_acres * 43560 ≈ impervious_sqft
    assert np.allclose(imp_acres * 43560.0, imp_sqft, atol=1e-3)


# ══════════════════════════════════════════════════════════════════════
#  Mode Choice
# ══════════════════════════════════════════════════════════════════════


def _mode_choice(data, vehicles_per_capita=0.8):
    """Call the reference with a 15-array ``_mc_data`` tuple and the knob."""
    return compute_mode_choice(*data, vehicles_per_capita)


@pytest.mark.slow
@given(_mc_data())
@_N_HYPOTHESIS
def test_mode_choice_shares_are_bounded(data):
    """Every share is a probability, and the split never under-claims.

    UrbanFootprint applies each non-auto sigmoid independently to what the
    internal capture left, so the four together can over-claim: ``auto`` is the
    difference, clamped at zero, and the five shares sum to at least 1 — exactly
    1 (the partition the ``assert_mode_share_sum`` audit enforces) whenever the
    clamp does not bind, which is the realistic case the test below pins. A
    parcel with no trips has no split at all: every share is NaN and every trip
    count is zero.
    """
    auto, transit, walk, bike, capture, s_auto, s_transit, s_walk, s_bike, s_cap = (
        _mode_choice(data)
    )
    total = data[0] + data[1] + data[2]
    split = total > 0
    for share in (s_auto, s_transit, s_walk, s_bike, s_cap):
        assert np.all(share[split] >= 0.0)
        assert np.all(share[split] <= 1.0 + 1e-9)
        assert np.all(np.isnan(share[~split]))
    for count in (auto, transit, walk, bike, capture):
        assert np.all(count[split] >= 0.0)
        assert np.all(count[~split] == 0.0)
    shares = s_auto + s_transit + s_walk + s_bike + s_cap
    assert np.all(shares[split] >= 1.0 - 1e-9)


@pytest.mark.slow
def test_mode_choice_partitions_a_realistic_canvas():
    """At realistic magnitudes the five shares partition the trips exactly.

    Sprawl-like, modest and dense parcels; the auto residual's zero clamp never
    binds here, which is the case the ``assert_mode_share_sum`` audit judges.
    """
    data = (
        np.array([120.0, 340.0, 900.0]),  # trips_hbw
        np.array([280.0, 800.0, 2100.0]),  # trips_hbo
        np.array([160.0, 460.0, 1200.0]),  # trips_nhb
        np.array([0.4, 1.6, 8.0]),  # area_gross_acres
        np.array([40.0, 180.0, 420.0]),  # intersection_density
        np.array([30.0, 220.0, 1400.0]),  # pop
        np.array([12.0, 90.0, 560.0]),  # hh
        np.array([0.0, 60.0, 900.0]),  # emp
        np.array([2.5, np.nan, 2.9]),  # household_size
        np.array([200.0, 2400.0, 18000.0]),  # qmb_pop
        np.array([0.0, 400.0, 6000.0]),  # qmb_emp
        np.array([20.0, 120.0, 400.0]),  # qmb_res_acres
        np.array([10.0, 40.0, 120.0]),  # qmb_emp_acres
        np.array([0.0, 10.0, 60.0]),  # qmb_mixed_acres
        np.array([0.0, 3000.0, 25000.0]),  # emp_1mile
    )
    auto, transit, walk, bike, capture, s_auto, s_transit, s_walk, s_bike, s_cap = (
        _mode_choice(data)
    )
    total = data[0] + data[1] + data[2]
    assert np.all(auto > 0.0)
    assert np.allclose(auto + transit + walk + bike + capture, total, atol=1e-6)
    assert np.allclose(s_auto + s_transit + s_walk + s_bike + s_cap, 1.0, atol=1e-9)


@pytest.mark.slow
@given(
    # From 1.0: the reference adds a log term only when its input is positive,
    # so an employment count below one is *penalised* relative to none at all
    # (ln(0.5) is negative) — an artefact of the guard, not a property worth
    # asserting. Real counts are whole jobs.
    st.lists(st.floats(1.0, 20000.0, allow_nan=False), min_size=2, max_size=10).map(
        lambda values: np.array(values, dtype=float)
    )
)
@_N_HYPOTHESIS
def test_mode_choice_walk_access_favours_walk(emp_1mile):
    """More employment within a mile raises the walk share, and lowers auto's.

    ``emp_1mile`` enters only the three walk log-odds, all with a positive
    coefficient, and no capture, transit or bike term — so the walk share is
    monotone in it, with the buffer context and the trips held equal. That is
    what makes the shares directly comparable across the draws.
    """
    n = len(emp_1mile)
    ones = np.ones(n)
    data = (
        ones * 400.0,  # trips_hbw
        ones * 900.0,  # trips_hbo
        ones * 500.0,  # trips_nhb
        ones * 2.0,  # area_gross_acres
        ones * 200.0,  # intersection_density
        ones * 200.0,  # pop
        ones * 80.0,  # hh
        ones * 100.0,  # emp
        ones * 2.5,  # household_size
        ones * 2000.0,  # qmb_pop
        ones * 600.0,  # qmb_emp
        ones * 100.0,  # qmb_res_acres
        ones * 40.0,  # qmb_emp_acres
        ones * 20.0,  # qmb_mixed_acres
        emp_1mile,
    )
    _, _, _, _, _, s_auto, _, s_walk, _, _ = _mode_choice(data)
    order = np.argsort(emp_1mile, kind="stable")
    assert np.all(np.diff(s_walk[order]) >= -1e-12)
    assert np.all(np.diff(s_auto[order]) <= 1e-12)


# ══════════════════════════════════════════════════════════════════════
#  VMT
# ══════════════════════════════════════════════════════════════════════


@pytest.mark.slow
@given(_triple(0, 50000, 0, 100.0, 0, 15000))
@_N_HYPOTHESIS
def test_vmt_formulas(triple):
    auto_trips, avg_trip_length_km, pop = triple
    vmt, vmt_pc, trip_mi, auto_out = compute_vmt(auto_trips, avg_trip_length_km, pop)
    assert np.all(vmt >= 0)
    assert np.all(vmt_pc >= 0)
    assert np.all(trip_mi >= 0)
    # Trip length is only converted; auto trips pass through unchanged.
    assert np.allclose(trip_mi, avg_trip_length_km * 0.621371, atol=1e-9)
    assert np.allclose(auto_out, auto_trips, atol=1e-9)
    assert np.allclose(vmt, auto_trips * trip_mi, atol=1e-3)
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
    co2e, co2e_annual, co2e_pc = compute_transport_ghg(vmt, pop)
    assert np.all(co2e >= 0)
    assert np.all(co2e_annual >= 0)
    assert np.all(co2e_pc >= 0)
    assert np.allclose(co2e, vmt * 0.411, atol=1e-6)
    # the annual column is what the yearly building/water/health models read
    assert np.allclose(co2e_annual, co2e * 365.0, atol=1e-6)
    co2e_adj, _, _ = compute_transport_ghg(vmt, pop, speed_adjust=True)
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
        walk,
        bike,
        length,
        auto,
        transit,
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
@given(_quint(0, 5e6, 0, 5e6, 0, 500, 0, 500))
@_N_HYPOTHESIS
def test_energy_demand_sum_and_intensity(quint):
    res_sqft, com_sqft, elec_eui, gas_eui, _ = quint
    er, gr, enr, gnr, total, intensity = compute_energy_demand(
        res_sqft,
        com_sqft,
        elec_eui,
        gas_eui,
    )
    assert np.all(total >= 0)
    assert np.allclose(total, er + gr + enr + gnr, atol=1e-6)
    assert np.all(intensity >= 0)
    mask = (res_sqft + com_sqft) > 0
    if np.any(mask):
        assert np.allclose(
            intensity[mask],
            total[mask] / (res_sqft + com_sqft)[mask],
            atol=1e-6,
        )


# ══════════════════════════════════════════════════════════════════════
#  Water Demand
# ══════════════════════════════════════════════════════════════════════


@pytest.mark.slow
@given(_wdata())
@_N_HYPOTHESIS
def test_water_demand_total_identity(data):
    pop, indoor_rate, emp, res_irr, com_irr, outdoor_rate = data
    ri, ro, ni, no, total, per_unit = compute_water_demand(
        pop,
        indoor_rate,
        emp,
        res_irr,
        com_irr,
        outdoor_rate,
    )
    assert np.all(total >= 0)
    assert np.allclose(total, ri + ro + ni + no, atol=1e-3)
    assert np.all(per_unit >= 0)
    mask = (pop + emp) > 0
    if np.any(mask):
        assert np.allclose(
            per_unit[mask],
            total[mask] / (pop + emp)[mask],
            atol=1e-6,
        )


# ══════════════════════════════════════════════════════════════════════
#  Building & Water GHG
# ══════════════════════════════════════════════════════════════════════


@pytest.mark.slow
@given(_ghg_data())
@_N_HYPOTHESIS
def test_building_water_ghg_identity(data):
    e_res, e_nonres, g_res, g_nonres, w_total, pop = data
    co2e_en, co2e_w, co2e_total, co2e_pc = compute_building_water_ghg(
        e_res,
        e_nonres,
        g_res,
        g_nonres,
        w_total,
        pop,
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
    (cultivated, yield_tons, market, cost, net, water_af, labor, trucks) = (
        compute_agriculture(ag_acres, dev_acres, is_rural)
    )
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
@given(_quint(0, 500, 0, 500, 0, 500, 0, 10000, 0, 100))
@_N_HYPOTHESIS
def test_trip_generation_activity_terms(quint):
    """Trips come from dwelling units by class and jobs by sector, additively.

    The blend of activity in each row is what the old per-form rate could not
    express: a mixed-use row (dwelling units AND jobs) has to produce both
    terms, and a row with jobs but no sector mix has to fall to the retail
    rate rather than to zero.
    """
    du_detsf, du_mf2to4, du_mf5p, emp, du_attsf = quint
    shares = [
        {}
        if employment == 0
        else {
            "retail_services": 40.0 + (i % 5) * 10.0,
            "office_services": 30.0,
            "accommodation": 30.0,
        }
        for i, employment in enumerate(emp)
    ]
    res, school, nonres, total, hbw, hbo, nhb = compute_trip_generation(
        du_detsf,
        du_mf2to4,
        du_mf5p,
        du_attsf,
        emp,
        shares,
    )
    assert np.all(res >= 0)
    assert np.all(school >= 0)
    assert np.all(nonres >= 0)
    assert np.all(total >= 0)
    assert np.all(hbw >= 0) and np.all(hbo >= 0) and np.all(nhb >= 0)
    assert np.allclose(
        res,
        du_detsf * 9.57 + du_mf2to4 * 6.65 + (du_mf5p + du_attsf) * 4.18,
        atol=1e-9,
    )
    assert np.allclose(school, res * 0.097, atol=1e-9)
    assert np.allclose(total, res + school + nonres, atol=1e-9)
    assert np.allclose(hbw + hbo + nhb, total, atol=1e-6)
    # Employment is the only source of non-residential trips.
    assert np.all(nonres[emp == 0] == 0)


def test_trip_generation_unattributed_jobs_fall_to_retail():
    """A built form with jobs and no sector mix prices them at the retail rate."""
    emp = np.array([100.0])
    _, _, nonres, _, _, _, _ = compute_trip_generation(
        np.array([0.0]),
        np.array([0.0]),
        np.array([0.0]),
        np.array([0.0]),
        emp,
        [{}],
    )
    assert np.allclose(nonres, 100.0 * 21.47)


# ══════════════════════════════════════════════════════════════════════
#  Internal Capture
# ══════════════════════════════════════════════════════════════════════


@pytest.mark.slow
@given(_ic_data())
@_N_HYPOTHESIS
def test_internal_capture_bounds(data):
    outbound, inbound, intra, frac, length, radius = data
    internal, capture, external = compute_internal_capture(
        outbound,
        inbound,
        intra,
        frac,
        length,
        radius,
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
        ("mode_choice", lambda: compute_mode_choice(*([e] * 15), 0.8)),
        ("vmt", lambda: compute_vmt(e, e, e)),
        ("transport_ghg", lambda: compute_transport_ghg(e, e)),
        ("impervious", lambda: compute_impervious_surface(e, e, e, e, e)),
        ("physical_activity", lambda: compute_physical_activity(e, e, e, e, e)),
        ("energy_demand", lambda: compute_energy_demand(e, e, e, e)),
        ("water_demand", lambda: compute_water_demand(e, e, e, e, e, e)),
        ("building_ghg", lambda: compute_building_water_ghg(e, e, e, e, e, e)),
        ("agriculture", lambda: compute_agriculture(e, e, e)),
        ("trip_generation", lambda: compute_trip_generation(e, e, e, e, e, [])),
    ]
    for name, fn in cases:
        result = fn()
        for arr in result if isinstance(result, tuple) else [result]:
            assert len(arr) == 0, f"{name}: expected empty array"
