"""Pure Python oracles for the analysis SQL models' formulas.

Each function mirrors a SQLMesh model's SELECT expressions exactly, and is only
ever used as the expected value in ``test_sql_parity.py`` — which runs the real
model and asserts its output matches. A mirror that drifts from the SQL shows up
there as a parity failure; it is never tested against itself.

The ``@deal.pre`` / ``@deal.post`` contracts document the mathematical
invariants and are enforced only when ``DEAL_ENABLED=1`` (``conftest.py``
disables them otherwise), so in CI they are executable documentation.

Naming convention: ``compute_<output>`` or ``compute_<model>_<output>``
matching the model or macro name.

All functions are pure: no I/O, no mutations.  numpy arrays are assumed
to be non-None and have matching lengths.
"""
# ruff: noqa: ARG005, PLR0913, PLR0917, ERA001

from __future__ import annotations

from typing import TYPE_CHECKING

import deal
import numpy as np

if TYPE_CHECKING:
    from collections.abc import Mapping
    from collections.abc import Sequence

# km -> mi. A physical constant, hardcoded in the SQL models rather than a
# scenario parameter (the `transport_km_to_mi` config variable is dead).
_MI_PER_KM = 0.621371

# ══════════════════════════════════════════════════════════════════════
#  Helper: safe coalesce
# ══════════════════════════════════════════════════════════════════════


def _c(arr: np.ndarray, default: float = 0.0) -> np.ndarray:
    """COALESCE equivalent: replace NaN with *default*.

    numpy NaN is the sentinel for "SQL NULL after COALESCE became 0.0".
    """
    return np.where(np.isnan(arr), default, arr)


def _fallback(nullable: np.ndarray, built_form: np.ndarray) -> np.ndarray:
    """``COALESCE(nullable, built_form, 0.0)`` over arrays.

    *nullable* is the zone-keyed expression, NaN wherever the parcel's climate
    zone has no baseline (or the parcel has no zone at all) — the same NULL SQL's
    NULL arithmetic produces. *built_form* is the pre-climate-zone built-form
    expression the models fall back to there, itself NaN-safe through ``_c``.
    """
    return np.where(np.isnan(nullable), _c(built_form), nullable)


def _nullable_nonneg(*arrays: np.ndarray) -> bool:
    """Every entry of each array is non-negative or NaN (the SQL NULL sentinel)."""
    return all(np.all(np.isnan(a) | (a >= 0)) for a in arrays)


# ══════════════════════════════════════════════════════════════════════
#  Fiscal — Property Tax  (fiscal_property_tax.sql)
# ══════════════════════════════════════════════════════════════════════


@deal.pre(lambda du, bsqt, res_val, nonres_val, rate: np.all(du >= 0))
@deal.pre(lambda du, bsqt, res_val, nonres_val, rate: np.all(bsqt >= 0))
@deal.pre(lambda du, bsqt, res_val, nonres_val, rate: rate > 0)
@deal.post(lambda result: np.all(result[0] >= 0))  # assessed_value_res
@deal.post(lambda result: np.all(result[1] >= 0))  # assessed_value_nonres
@deal.post(lambda result: np.all(result[2] >= 0))  # property_tax_revenue
def compute_property_tax(
    dwelling_units_total: np.ndarray,
    building_sqft_commercial: np.ndarray,
    res_assessed_value_per_du: float = 350000.0,
    nonres_assessed_value_per_sqft: float = 150.0,
    property_tax_rate: float = 1.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """SQL: ``fiscal_property_tax`` — property tax from assessed value.

    Returns (assessed_value_res, assessed_value_nonres, property_tax_revenue).
    """
    av_res = _c(dwelling_units_total * res_assessed_value_per_du)
    av_nonres = _c(building_sqft_commercial * nonres_assessed_value_per_sqft)
    revenue = _c(
        (
            _c(dwelling_units_total * res_assessed_value_per_du)
            + _c(building_sqft_commercial * nonres_assessed_value_per_sqft)
        )
        * property_tax_rate
        / 100.0
    )
    return av_res, av_nonres, revenue


# ══════════════════════════════════════════════════════════════════════
#  Fiscal — Service Costs  (fiscal_service_costs.sql)
# ══════════════════════════════════════════════════════════════════════


@deal.pre(lambda du, pop, emp: np.all(du >= 0))
@deal.pre(lambda du, pop, emp: np.all(pop >= 0))
@deal.pre(lambda du, pop, emp: np.all(emp >= 0))
@deal.post(lambda result: np.all(result[0] >= 0))
@deal.post(lambda result: np.all(result[1] >= 0))
@deal.post(lambda result: np.all(result[2] >= 0))
@deal.post(lambda result: np.all(result[3] >= 0))
@deal.post(
    lambda result: np.all(
        np.abs(result[3] - (result[0] + result[1] + result[2])) < 1e-6
    )
)
def compute_service_costs(
    dwelling_units_total: np.ndarray,
    population: np.ndarray,
    employment_total: np.ndarray,
    cost_per_du: float = 5000.0,
    cost_per_capita: float = 2000.0,
    cost_per_employee: float = 1500.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """SQL: ``fiscal_service_costs`` — public service cost components.

    Returns (schools, public_safety, roads, total).
    Post-condition: total == schools + public_safety + roads (within fp tolerance).
    """
    schools = _c(dwelling_units_total * cost_per_du)
    safety = _c(population * cost_per_capita)
    roads = _c(employment_total * cost_per_employee)
    total = schools + safety + roads
    return schools, safety, roads, total


# ══════════════════════════════════════════════════════════════════════
#  Land Consumption — Impervious Surface  (land_consumption.sql)
# ══════════════════════════════════════════════════════════════════════


@deal.pre(lambda bsqt, du, emp, gross_acres, dev_acres: np.all(bsqt >= 0))
@deal.pre(lambda bsqt, du, emp, gross_acres, dev_acres: np.all(du >= 0))
@deal.pre(lambda bsqt, du, emp, gross_acres, dev_acres: np.all(emp >= 0))
@deal.pre(lambda bsqt, du, emp, gross_acres, dev_acres: np.all(gross_acres >= 0))
@deal.pre(lambda bsqt, du, emp, gross_acres, dev_acres: np.all(dev_acres >= 0))
@deal.post(lambda result: np.all(result[0] >= 0))  # impervious_sqft
@deal.post(lambda result: np.all(result[1] >= 0))  # impervious_acres
@deal.post(lambda result: np.all(result[2] >= 0))  # pervious_acres
@deal.post(lambda result: np.all(result[3] >= 0))  # impervious_pct
@deal.post(lambda result: result[3].shape == result[0].shape)
@deal.post(
    lambda result: np.all(
        np.abs(result[1] * 43560.0 - result[0])
        < 1e-3  # impervious_acres * 43560 ≈ impervious_sqft
        | (result[1] == 0)
    )
)
def compute_impervious_surface(
    building_sqft_total: np.ndarray,
    dwelling_units_total: np.ndarray,
    employment_total: np.ndarray,
    gross_acres: np.ndarray,
    acres_developed: np.ndarray,
    ground_coverage_factor: float = 0.6,
    parking_per_unit: float = 0.5,
    parking_per_employee: float = 0.2,
    parking_space_sqft: float = 300.0,
    row_fraction: float = 0.15,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """SQL: ``land_consumption`` L2 impervious surface estimation.

    Returns (impervious_sqft, impervious_acres, pervious_acres, impervious_pct).
    """
    building_ft = _c(building_sqft_total * ground_coverage_factor)
    parking = _c(
        (
            _c(dwelling_units_total * parking_per_unit)
            + _c(employment_total * parking_per_employee)
        )
        * parking_space_sqft
    )
    row_sqft = _c(acres_developed * row_fraction * 43560.0)

    imp_sqft = building_ft + parking + row_sqft
    imp_acres = imp_sqft / 43560.0

    pervious = np.where(
        gross_acres > 0,
        np.maximum(gross_acres - imp_acres, 0.0),
        0.0,
    )
    imp_pct = np.where(
        gross_acres > 0,
        imp_acres / gross_acres * 100.0,
        0.0,
    )
    return imp_sqft, imp_acres, pervious, imp_pct


# ══════════════════════════════════════════════════════════════════════
#  Mode Choice  (mode_choice.sql)
# ══════════════════════════════════════════════════════════════════════

# The bike sigmoid's five coefficients are the scenario's ``transport_bike_*``
# parameters; these are ``ANALYSIS_PARAMETERS``' defaults, which is what a
# parity run renders when it passes no variables of its own. Keyed by parameter
# name because that is what the drift guard in
# ``tests/workspace/test_module_registry.py`` compares them against — this
# module is deliberately Django-free, so it cannot read the registry itself.
# ``transport_vehicles_per_capita`` is the same kind of default and travels as
# an explicit argument instead, since the model substitutes it in one place.
BIKE_PARAMETER_DEFAULTS: dict[str, float] = {
    "transport_bike_asc": -6.5,
    "transport_bike_beta_density": 0.20,
    "transport_bike_beta_design": 0.20,
    "transport_bike_beta_hhsize": -0.6,
    "transport_bike_beta_veh": -0.9,
}

# The two link helpers the hierarchical sigmoid needs. Both are shared by the
# reference and the SQL model's intent: the guards are what make ln(0) a
# skipped term rather than a -infinity, and 1/(1+exp(-x)) is the same number as
# exp(x)/(exp(x)+1) without overflowing.


def _gln(x: np.ndarray) -> np.ndarray:
    """The reference's ``if x > 0: term * log(x) else: 0.0`` — a guarded ln."""
    x = np.asarray(x, dtype=float)
    positive = x > 0
    return np.where(positive, np.log(np.where(positive, x, 1.0)), 0.0)


def _sigma(x: np.ndarray) -> np.ndarray:
    """Logistic link: ``1 / (1 + exp(-x))``."""
    return 1.0 / (1.0 + np.exp(-np.asarray(x, dtype=float)))


def _mode_choice_inputs_aligned(
    trips_hbw: np.ndarray,
    trips_hbo: np.ndarray,
    trips_nhb: np.ndarray,
    area_gross_acres: np.ndarray,
    intersection_density: np.ndarray,
    pop: np.ndarray,
    hh: np.ndarray,
    emp: np.ndarray,
    household_size: np.ndarray,
    qmb_pop: np.ndarray,
    qmb_emp: np.ndarray,
    qmb_res_acres: np.ndarray,
    qmb_emp_acres: np.ndarray,
    qmb_mixed_acres: np.ndarray,
    emp_1mile: np.ndarray,
    vehicles_per_capita: float,
) -> bool:
    """``@deal.pre``: purpose trips are counts, and every input is per-parcel.

    Named rather than a lambda so the sixteen-parameter formatter keeps it
    readable (a lambda's parameter list cannot carry the magic trailing comma
    that would otherwise force one name per line).
    """
    length = len(trips_hbw)
    return all(
        len(array) == length
        for array in (
            trips_hbo,
            trips_nhb,
            area_gross_acres,
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
        )
    ) and all(
        np.all(_c(np.asarray(trips, dtype=float)) >= 0)
        for trips in (trips_hbw, trips_hbo, trips_nhb)
    )


@deal.pre(_mode_choice_inputs_aligned)
@deal.post(lambda result: len(result) == 10)
@deal.post(lambda result: np.all(result[0] >= 0) and np.all(result[2] >= 0))
@deal.post(
    lambda result: np.all(
        np.isnan(result[5])
        | ((result[5] + result[6] + result[7] + result[8] + result[9]) >= 1.0 - 1e-9)
    )
)
def compute_mode_choice(
    trips_hbw: np.ndarray,
    trips_hbo: np.ndarray,
    trips_nhb: np.ndarray,
    area_gross_acres: np.ndarray,
    intersection_density: np.ndarray,
    pop: np.ndarray,
    hh: np.ndarray,
    emp: np.ndarray,
    household_size: np.ndarray,
    qmb_pop: np.ndarray,
    qmb_emp: np.ndarray,
    qmb_res_acres: np.ndarray,
    qmb_emp_acres: np.ndarray,
    qmb_mixed_acres: np.ndarray,
    emp_1mile: np.ndarray,
    vehicles_per_capita: float,
) -> tuple[
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
]:
    """SQL: ``mode_choice`` — UrbanFootprint's hierarchical sigmoid split.

    Mirrors the SQL model's purpose-by-purpose sequence: internal capture,
    then walk / transit / bike on what the capture left, with auto as the
    residual. The coefficients are UrbanFootprint's published log-odds
    constants (``vmt_model_constants.py``); the transit-accessibility terms
    (``emp30m_transit``, ``hh_within_quarter_mile_trans``) are dropped in both
    because BrewGIS has no transit network to source them.

    ``vehicles_per_capita`` is the single scalar knob (the scenario's
    ``transport_vehicles_per_capita``); the bike sigmoid's five coefficients
    are the scenario's ``transport_bike_*`` parameters, taken from
    ``BIKE_PARAMETER_DEFAULTS``.

    Returns (trips_auto, trips_transit, trips_walk, trips_bike,
             trips_internal_capture, share_auto, share_transit, share_walk,
             share_bike, share_internal_capture). A parcel with zero trips has
             no split to make: its shares are NaN (the SQL side divides by a
             NULLIF-guarded total) while its trip counts are all zero.
    """
    if len(trips_hbw) == 0:
        empty = np.array([], dtype=float)
        return (empty,) * 10

    # The SQL wraps each purpose's trips in COALESCE(..., 0.0); NaN is this
    # module's sentinel for a NULL the coalesce already replaced.
    trips_hbw = _c(np.asarray(trips_hbw, dtype=float))
    trips_hbo = _c(np.asarray(trips_hbo, dtype=float))
    trips_nhb = _c(np.asarray(trips_nhb, dtype=float))

    area_sqmi = _c(np.asarray(area_gross_acres, dtype=float)) / 640.0
    # intersections per km2 -> per square mile
    int_sqmi = _c(np.asarray(intersection_density, dtype=float)) * 2.58998811
    pop_m = _c(np.asarray(pop, dtype=float))
    emp_cell = _c(np.asarray(emp, dtype=float))
    emp_1m = _c(np.asarray(emp_1mile, dtype=float))
    qmb_pop_m = _c(np.asarray(qmb_pop, dtype=float))
    qmb_emp_m = _c(np.asarray(qmb_emp, dtype=float))

    # hh_avg_size = COALESCE(NULLIF(pop / NULLIF(hh, 0), 0), household_size, 2.577)
    hh_arr = np.asarray(hh, dtype=float)
    ratio = np.where(hh_arr != 0, pop_m / np.where(hh_arr != 0, hh_arr, 1.0), np.nan)
    ratio = np.where(np.isnan(ratio) | (ratio == 0), np.nan, ratio)
    hs = np.asarray(household_size, dtype=float)
    hh_size = np.where(~np.isnan(ratio), ratio, np.where(~np.isnan(hs), hs, 2.577))

    veh = float(vehicles_per_capita)
    # Broadcast: every logit below is a length-n array, so the vehicles term has
    # to be one too (``np.column_stack`` rejects a 0-d entry).
    ln_veh = np.full_like(trips_hbw, _gln(np.asarray(veh, dtype=float)))

    # pop+emp per square mile over the quarter-mile acres, and the jobs-vs-
    # population mix (the reference's tMXD_pop_emp_m_sq / tMXD_jobs_v_pop).
    pop_emp_sqmi = (
        (qmb_pop_m + qmb_emp_m)
        / np.maximum(
            _c(np.asarray(qmb_res_acres, dtype=float))
            + _c(np.asarray(qmb_emp_acres, dtype=float))
            + _c(np.asarray(qmb_mixed_acres, dtype=float)),
            1e-9,
        )
        * 640.0
    )
    mix = np.maximum(
        1.0
        - np.abs(0.2 * qmb_pop_m - qmb_emp_m)
        / np.maximum(0.2 * qmb_pop_m + qmb_emp_m, 1e-9),
        0.01,
    )

    ln_mix = _gln(mix)
    ln_area_sqmi = _gln(area_sqmi)
    ln_int_sqmi = _gln(int_sqmi)
    ln_hh_size = _gln(hh_size)
    ln_emp_cell = _gln(emp_cell)
    ln_pop_emp_sqmi = _gln(pop_emp_sqmi)
    ln_emp_1m = _gln(emp_1m)

    # One column per purpose: hbw, hbo, nhb.
    icpm_logit = np.column_stack(
        [
            -1.75 + 0.389 * ln_mix - 1.33 * ln_hh_size - 0.99 * ln_veh,
            -2.43
            + 0.486 * ln_area_sqmi
            + 0.399 * ln_mix
            + 0.385 * ln_int_sqmi
            - 0.867 * ln_hh_size
            - 0.59 * ln_veh,
            -5.32
            + 0.208 * ln_emp_cell
            + 0.468 * ln_area_sqmi
            + 0.638 * ln_int_sqmi
            - 0.237 * ln_hh_size
            - 0.163 * ln_veh,
        ]
    )
    wtpm_logit = np.column_stack(
        [
            -5.55
            + 0.226 * ln_mix
            + 0.385 * ln_emp_1m
            - 1.57 * ln_hh_size
            - 1.84 * ln_veh,
            -10.96
            - 0.415 * ln_area_sqmi
            + 0.37 * ln_pop_emp_sqmi
            + 0.219 * ln_mix
            + 0.45 * ln_emp_1m
            - 0.486 * ln_hh_size
            - 0.768 * ln_veh,
            -15.09
            + 0.377 * ln_pop_emp_sqmi
            + 0.803 * ln_int_sqmi
            + 0.44 * ln_emp_1m
            - 0.281 * ln_hh_size
            - 0.242 * ln_veh,
        ]
    )
    ttpm_logit = np.column_stack(
        [
            -8.05 + 1.12 * ln_int_sqmi - 1.14 * ln_hh_size - 1.68 * ln_veh,
            -6.08 + 0.324 * ln_pop_emp_sqmi - 0.958 * ln_hh_size - 1.09 * ln_veh,
            -2.69 - 0.34 * ln_veh,
        ]
    )
    btpm_logit = (
        BIKE_PARAMETER_DEFAULTS["transport_bike_asc"]
        + BIKE_PARAMETER_DEFAULTS["transport_bike_beta_density"] * ln_pop_emp_sqmi
        + BIKE_PARAMETER_DEFAULTS["transport_bike_beta_design"] * ln_int_sqmi
        + BIKE_PARAMETER_DEFAULTS["transport_bike_beta_hhsize"] * ln_hh_size
        + BIKE_PARAMETER_DEFAULTS["transport_bike_beta_veh"] * ln_veh
    )

    trips = np.column_stack([trips_hbw, trips_hbo, trips_nhb])
    icpm = trips * _sigma(icpm_logit)
    remaining = trips - icpm
    walk = remaining * _sigma(wtpm_logit)
    transit = remaining * _sigma(ttpm_logit)
    bike = remaining * _sigma(btpm_logit)[:, np.newaxis]
    auto = np.maximum(0.0, remaining - walk - transit - bike)

    trips_auto = auto.sum(axis=1)
    trips_transit = transit.sum(axis=1)
    trips_walk = walk.sum(axis=1)
    trips_bike = bike.sum(axis=1)
    trips_capture = icpm.sum(axis=1)

    total = trips.sum(axis=1)
    # NULLIF(total, 0): a zero-trip parcel has no share to compute.
    denom = np.where(total != 0, total, np.nan)

    return (
        trips_auto,
        trips_transit,
        trips_walk,
        trips_bike,
        trips_capture,
        trips_auto / denom,
        trips_transit / denom,
        trips_walk / denom,
        trips_bike / denom,
        trips_capture / denom,
    )


# ══════════════════════════════════════════════════════════════════════
#  VMT  (vmt.sql)
# ══════════════════════════════════════════════════════════════════════


@deal.pre(lambda auto_trips, avg_trip_length_km, pop: np.all(auto_trips >= 0))
@deal.pre(lambda auto_trips, avg_trip_length_km, pop: np.all(avg_trip_length_km >= 0))
@deal.pre(lambda auto_trips, avg_trip_length_km, pop: np.all(pop >= 0))
@deal.post(lambda result: np.all(result[0] >= 0))  # vmt_total
@deal.post(lambda result: np.all(result[1] >= 0))  # vmt_per_capita
@deal.post(lambda result: np.all(result[2] >= 0))  # avg_trip_length_mi
@deal.post(lambda result: np.all(result[3] >= 0))  # auto_trips
@deal.post(lambda result: np.all(result[0] >= result[3] * result[2]))  # vmt >= trips*mi
def compute_vmt(
    auto_trips: np.ndarray,
    avg_trip_length_km: np.ndarray,
    population: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """SQL: ``vmt`` — vehicle miles traveled from mode-choice auto trips and the
    parcel one-way trip length.

    ``avg_trip_length_km`` is the ``trip_lengths`` model's value — the region's
    reference zone length where it has one, else the gravity length scaled to
    the regional target — converted to miles with the km -> mi constant the SQL
    model hardcodes; ``vmt_total`` is then trips x miles. There is no circuity
    factor on top of it: a reference length is already a network distance.

    Returns (vmt_total, vmt_per_capita, avg_trip_length_mi, auto_trips).
    """
    auto_trips = np.asarray(auto_trips, dtype=float)
    avg_trip_length_km = np.asarray(avg_trip_length_km, dtype=float)
    vmt = auto_trips * avg_trip_length_km * _MI_PER_KM
    vmt_per_cap = np.where(population > 0, vmt / population, 0.0)
    trip_len_mi = avg_trip_length_km * _MI_PER_KM
    return vmt, vmt_per_cap, trip_len_mi, auto_trips


# ══════════════════════════════════════════════════════════════════════
#  Transport GHG  (transport_ghg.sql)
# ══════════════════════════════════════════════════════════════════════


@deal.pre(lambda vmt, pop: np.all(vmt >= 0))
@deal.pre(lambda vmt, pop: np.all(pop >= 0))
@deal.post(lambda result: np.all(result[0] >= 0))  # co2e_total_kg
@deal.post(lambda result: np.all(result[1] >= 0))  # co2e_annual_kg
@deal.post(lambda result: np.all(result[2] >= 0))  # co2e_per_capita_kg
def compute_transport_ghg(
    vmt_total: np.ndarray,
    population: np.ndarray,
    co2_per_mile: float = 0.411,
    speed_adjust: bool = False,
    days_per_year: float = 365.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """SQL: ``transport_ghg`` — CO₂e from VMT.

    Returns (co2e_total_kg, co2e_annual_kg, co2e_per_capita_kg): the daily
    figure, the same figure over ``days_per_year`` (what the yearly building,
    water and health models read), and the daily per-capita figure.
    """
    factor = 1.15 if speed_adjust else 1.0
    co2e = vmt_total * co2_per_mile * factor
    co2e_pc = np.where(population > 0, co2e / population, 0.0)
    return co2e, co2e * days_per_year, co2e_pc


# ══════════════════════════════════════════════════════════════════════
#  Physical Activity  (physical_activity.sql)
# ══════════════════════════════════════════════════════════════════════


@deal.pre(lambda wk, bk, wlen, blen, auto, transit: np.all(wk >= 0))
@deal.pre(lambda wk, bk, wlen, blen, auto, transit: np.all(bk >= 0))
@deal.pre(lambda wk, bk, wlen, blen, auto, transit: np.all(wlen >= 0))
@deal.pre(lambda wk, bk, wlen, blen, auto, transit: np.all(blen >= 0))
@deal.pre(lambda wk, bk, wlen, blen, auto, transit: np.all(auto >= 0))
@deal.pre(lambda wk, bk, wlen, blen, auto, transit: np.all(transit >= 0))
@deal.post(lambda result: np.all(result[0] >= 0))  # walk_met_hours
@deal.post(lambda result: np.all(result[1] >= 0))  # bike_met_hours
@deal.post(lambda result: np.all(result[2] >= 0))  # total_met_hours
@deal.post(lambda result: np.all(result[5] >= 0))  # active_trip_share
@deal.post(lambda result: np.all(result[5] <= 1.0 + 1e-10))
@deal.post(lambda result: np.all(np.abs(result[2] - (result[0] + result[1])) < 1e-6))
def compute_physical_activity(
    walk_trips: np.ndarray,
    bike_trips: np.ndarray,
    walk_trip_length_km: float,
    bike_trip_length_km: float,
    auto_trips: np.ndarray,
    transit_trips: np.ndarray,
    walk_met: float = 3.5,
    bike_met: float = 6.0,
    walk_speed_kmh: float = 4.8,
    bike_speed_kmh: float = 16.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """SQL: ``physical_activity`` — MET-hours from active transport.

    Each active mode uses its own mean one-way trip distance; the region's
    vehicle trip length is not a walking or cycling distance.

    Returns (walk_met_hours, bike_met_hours, total_met_hours,
             walk_trips, bike_trips, active_trip_share).
    """
    walk_met_h = _c(walk_trips * (walk_trip_length_km / walk_speed_kmh) * walk_met)
    bike_met_h = _c(bike_trips * (bike_trip_length_km / bike_speed_kmh) * bike_met)
    total_met = walk_met_h + bike_met_h

    total_trips = _c(walk_trips) + _c(bike_trips) + _c(auto_trips) + _c(transit_trips)
    active_share = np.where(
        total_trips > 0,
        (_c(walk_trips) + _c(bike_trips)) / total_trips,
        0.0,
    )
    return walk_met_h, bike_met_h, total_met, walk_trips, bike_trips, active_share


# ══════════════════════════════════════════════════════════════════════
#  Energy Demand  (energy_demand.sql)
# ══════════════════════════════════════════════════════════════════════


@deal.pre(lambda *args, **kwargs: _nullable_nonneg(*args))
@deal.post(lambda result: np.all(result[0] >= 0))  # energy_electricity_res
@deal.post(lambda result: np.all(result[1] >= 0))  # energy_gas_res
@deal.post(lambda result: np.all(result[2] >= 0))  # energy_electricity_nonres
@deal.post(lambda result: np.all(result[3] >= 0))  # energy_gas_nonres
@deal.post(lambda result: np.all(result[4] >= 0))  # energy_total
@deal.post(lambda result: np.all(result[5] >= 0))  # energy_intensity
@deal.post(
    lambda result: np.all(
        np.abs(result[4] - (result[0] + result[1] + result[2] + result[3])) < 1e-6
    )
)
def compute_energy_demand(
    du: np.ndarray,
    du_elec_rate: np.ndarray,
    du_gas_rate: np.ndarray,
    com_area: np.ndarray,
    com_elec_rate: np.ndarray,
    com_gas_rate: np.ndarray,
    building_sqft_residential: np.ndarray,
    building_sqft_commercial: np.ndarray,
    electricity_eui: np.ndarray,
    gas_eui: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """SQL: ``energy_demand`` — kWh/year by fuel type, keyed on the CEC zone.

    Residential demand is the end state's dwelling units by housing class at the
    parcel's CEC Building Climate Zone per-dwelling-unit site intensity; commercial
    demand is its floor area by use at the zone's per-square-foot intensity. Gas is
    published in therms and returned in kWh at 29.3071 kWh/therm.

    The rate matrices are ``(n, 4)`` (dwelling units: detsf_ll, detsf_sl, attsf, mf)
    and ``(n, 11)`` (commercial uses, in ``energy_demand.sql``'s order), and a NaN
    entry is the SQL NULL of a parcel whose zone the baseline does not cover — the
    same signal ``_fallback`` uses to reproduce the model's COALESCE onto the built
    form's flat EUI, which is what a parcel outside California keeps.

    Returns (elec_res, gas_res, elec_nonres, gas_nonres, total, intensity_kwh_per_sqft).
    """
    sqft_to_m2 = 0.092903
    kwh_per_therm = 29.3071

    # Zone expression: NULL (NaN) whenever any rate it needs is NULL, exactly as
    # SQL's NULL arithmetic propagates — 0.0 * NULL is NULL, not zero.
    res_elec_zone = (du * du_elec_rate).sum(axis=1)
    res_gas_zone = (du * du_gas_rate).sum(axis=1) * kwh_per_therm
    nonres_elec_zone = (com_area * com_elec_rate).sum(axis=1)
    nonres_gas_zone = (com_area * com_gas_rate).sum(axis=1) * kwh_per_therm

    res_elec = _fallback(
        res_elec_zone, building_sqft_residential * sqft_to_m2 * electricity_eui
    )
    res_gas = _fallback(res_gas_zone, building_sqft_residential * sqft_to_m2 * gas_eui)
    nonres_elec = _fallback(
        nonres_elec_zone, building_sqft_commercial * sqft_to_m2 * electricity_eui
    )
    nonres_gas = _fallback(
        nonres_gas_zone, building_sqft_commercial * sqft_to_m2 * gas_eui
    )

    total = res_elec + res_gas + nonres_elec + nonres_gas
    total_sqft = _c(building_sqft_residential) + _c(building_sqft_commercial)
    intensity = np.where(total_sqft > 0, total / total_sqft, 0.0)
    return res_elec, res_gas, nonres_elec, nonres_gas, total, intensity


# ══════════════════════════════════════════════════════════════════════
#  Water Demand  (water_demand.sql)
# ══════════════════════════════════════════════════════════════════════


@deal.pre(lambda *args, **kwargs: _nullable_nonneg(*args))
@deal.post(lambda result: np.all(result[0] >= 0))  # water_demand_res_indoor
@deal.post(lambda result: np.all(result[1] >= 0))  # water_demand_res_outdoor
@deal.post(lambda result: np.all(result[2] >= 0))  # water_demand_nonres_indoor
@deal.post(lambda result: np.all(result[3] >= 0))  # water_demand_nonres_outdoor
@deal.post(lambda result: np.all(result[4] >= 0))  # water_demand_total
@deal.post(lambda result: np.all(result[5] >= 0))  # water_demand_per_unit
@deal.post(
    lambda result: np.all(
        np.abs(result[4] - (result[0] + result[1] + result[2] + result[3])) < 1e-6
    )
)
def compute_water_demand(
    population: np.ndarray,
    indoor_water_rate: np.ndarray,
    employment_total: np.ndarray,
    res_irrigated_area: np.ndarray,
    com_irrigated_area: np.ndarray,
    annual_eto_mm: np.ndarray,
    outdoor_water_rate: np.ndarray,
    nonres_indoor_water_rate: float = 40.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """SQL: ``water_demand`` — liters/year by category.

    Indoor demand is the end state's own population (not households times a
    household size), outdoor demand the end state's own irrigated acres at the
    parcel's CIMIS ETo-zone reference evapotranspiration depth (mm/year, which is
    liters per square metre per year).

    A NaN *annual_eto_mm* is the SQL NULL of a parcel in no ETo zone (outside
    California): its outdoor terms fall back to the built form's flat
    ``outdoor_water_rate``, the model's COALESCE onto the rate it used before ETo
    replaced it.

    Returns (res_indoor, res_outdoor, nonres_indoor, nonres_outdoor,
             total, per_unit).
    """
    depth = _fallback(annual_eto_mm, outdoor_water_rate)
    res_in = _c(population) * _c(indoor_water_rate) * 365.0
    res_out = _c(res_irrigated_area) * 4046.8564224 * depth
    nonres_in = _c(employment_total) * nonres_indoor_water_rate * 365.0
    nonres_out = _c(com_irrigated_area) * 4046.8564224 * depth

    total = res_in + res_out + nonres_in + nonres_out
    per_unit = np.where(
        _c(population) + _c(employment_total) > 0,
        total / (_c(population) + _c(employment_total)),
        0.0,
    )
    return res_in, res_out, nonres_in, nonres_out, total, per_unit


# ══════════════════════════════════════════════════════════════════════
#  Building & Water GHG  (building_water_ghg.sql)
# ══════════════════════════════════════════════════════════════════════


@deal.pre(
    lambda e_res, e_nonres, g_res, g_nonres, w_total, pop: (
        np.all(e_res >= 0) & np.all(e_nonres >= 0)
    )
)
@deal.pre(
    lambda e_res, e_nonres, g_res, g_nonres, w_total, pop: (
        np.all(g_res >= 0) & np.all(g_nonres >= 0)
    )
)
@deal.pre(lambda e_res, e_nonres, g_res, g_nonres, w_total, pop: np.all(w_total >= 0))
@deal.pre(lambda e_res, e_nonres, g_res, g_nonres, w_total, pop: np.all(pop >= 0))
@deal.post(lambda result: np.all(result[0] >= 0))  # co2e_energy_total_kg
@deal.post(lambda result: np.all(result[1] >= 0))  # co2e_water_total_kg
@deal.post(lambda result: np.all(result[2] >= 0))  # co2e_total_kg
@deal.post(lambda result: np.all(result[3] >= 0))  # co2e_per_capita_kg
@deal.post(lambda result: np.all(np.abs(result[2] - (result[0] + result[1])) < 1e-6))
def compute_building_water_ghg(
    energy_electricity_res: np.ndarray,
    energy_electricity_nonres: np.ndarray,
    energy_gas_res: np.ndarray,
    energy_gas_nonres: np.ndarray,
    water_demand_total: np.ndarray,
    population: np.ndarray,
    egrid_co2_per_kwh: float = 0.417,
    gas_co2_per_kwh: float = 0.181,
    water_supply_kwh_per_mg: float = 1427.0,
    wastewater_kwh_per_mg: float = 1911.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """SQL: ``building_water_ghg`` — CO₂e from energy + water.

    Returns (co2e_energy_total_kg, co2e_water_total_kg,
             co2e_total_kg, co2e_per_capita_kg).
    """
    elec = _c(energy_electricity_res + energy_electricity_nonres)
    gas = _c(energy_gas_res + energy_gas_nonres)
    co2e_energy = elec * egrid_co2_per_kwh + gas * gas_co2_per_kwh

    co2e_water = np.where(
        _c(water_demand_total) > 0,
        _c(water_demand_total)
        / 3785411.8
        * (water_supply_kwh_per_mg + wastewater_kwh_per_mg)
        * egrid_co2_per_kwh,
        0.0,
    )
    co2e_total = co2e_energy + co2e_water
    co2e_pc = np.where(population > 0, co2e_total / population, 0.0)
    return co2e_energy, co2e_water, co2e_total, co2e_pc


# ══════════════════════════════════════════════════════════════════════
#  Agriculture  (agriculture.sql)
# ══════════════════════════════════════════════════════════════════════


@deal.pre(lambda ag_acres, dev_acres, rural: np.all(ag_acres >= 0))
@deal.pre(lambda ag_acres, dev_acres, rural: np.all(dev_acres >= 0))
@deal.post(lambda result: np.all(result[0] >= 0))  # acres_cultivated
@deal.post(lambda result: np.all(result[1] >= 0))  # crop_yield_tons
@deal.post(lambda result: np.all(result[2] >= 0))  # market_value
@deal.post(lambda result: np.all(result[3] >= 0))  # production_cost
@deal.post(
    lambda result: np.all(
        np.abs(result[4] - (result[2] - result[3]))
        < 1e-6  # net_return = market - cost
        | (result[2] == 0)
        | (result[3] == 0)
    )
)
@deal.post(lambda result: np.all(result[5] >= 0))  # water_consumption_af
@deal.post(lambda result: np.all(result[6] >= 0))  # labor_hours
@deal.post(lambda result: np.all(result[7] >= 0))  # truck_trips
def compute_agriculture(
    parcel_acres_agriculture: np.ndarray,
    acres_developed: np.ndarray,
    is_rural: np.ndarray,  # bool array: land_dev_category == 'rural'
    crop_yield_per_acre: float = 8.0,
    crop_market_price_per_ton: float = 200.0,
    crop_production_cost_per_acre: float = 800.0,
    crop_water_per_acre_af: float = 3.0,
    crop_labor_hours_per_acre: float = 15.0,
    crop_truck_trips_per_acre: float = 2.0,
) -> tuple[
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
]:
    """SQL: ``agriculture`` — crop yield, value, resource use.

    Returns (acres_cultivated, crop_yield_tons, market_value,
             production_cost, net_return, water_consumption_af,
             labor_hours, truck_trips).
    """
    ag = _c(parcel_acres_agriculture)
    dev = _c(acres_developed)
    rural = is_rural.astype(bool)
    cultivated = np.where(
        ag > 0,
        ag,
        np.where(rural & (dev > 0), dev, 0.0),
    )
    yield_tons = cultivated * crop_yield_per_acre
    market_val = cultivated * crop_yield_per_acre * crop_market_price_per_ton
    prod_cost = cultivated * crop_production_cost_per_acre
    net = market_val - prod_cost
    water_af = cultivated * crop_water_per_acre_af
    labor = cultivated * crop_labor_hours_per_acre
    trucks = cultivated * crop_truck_trips_per_acre
    return cultivated, yield_tons, market_val, prod_cost, net, water_af, labor, trucks


# ══════════════════════════════════════════════════════════════════════
#  Trip Generation  (trip_generation.sql)
# ══════════════════════════════════════════════════════════════════════


# Sector name -> the employment bucket the SQL groups it into
# (``trip_generation.sql``, CTE ``bucket_weights``). Deliberately a second,
# independent copy: the SQL writes this mapping as literal key lists, and a
# parity test can only catch a drift between the two if they are not the same
# object.
TRIP_SECTOR_BUCKETS: dict[str, str] = {
    "retail_services": "retail",
    "other_services": "retail",
    "restaurant": "food",
    "accommodation": "food",
    "arts_entertainment": "arts",
    "office_services": "office",
    "medical_services": "office",
    "public_admin": "public",
    "education": "public",
    "manufacturing": "industry",
    "wholesale": "industry",
    "transport_warehousing": "industry",
    "construction": "industry",
    "utilities": "industry",
    "agriculture": "industry",
    "military": "industry",
}

# Trips per job per day, per bucket. UrbanFootprint's rates
# (vmt_raw_trip_generation.py); `retail` is also the rate an unattributed job
# and a sector name outside TRIP_SECTOR_BUCKETS both fall to.
TRIP_BUCKET_RATES: dict[str, float] = {
    "retail": 21.47,
    "food": 37.5,
    "arts": 10.0,
    "office": 3.32,
    "public": 3.32,
    "industry": 3.02,
}


def trip_employment(
    employment: float, sector_shares: Mapping[str, float] | None
) -> float:
    """Daily employment trips for *employment* jobs under *sector_shares*.

    Shares are percentages of the jobs and are normalized over the sectors the
    built form declares — SACOG's ``pct_*`` columns leave a residual for
    sectors it does not publish. No usable share at all puts every job on the
    retail rate, which is what an unrecognised sector name gets too.
    """
    weights = {k: float(v) for k, v in (sector_shares or {}).items() if v}
    total_weight = sum(weights.values())
    if employment <= 0:
        return 0.0
    if total_weight <= 0:
        return employment * TRIP_BUCKET_RATES["retail"]
    return sum(
        employment
        * weight
        / total_weight
        * TRIP_BUCKET_RATES[TRIP_SECTOR_BUCKETS[sector]]
        for sector, weight in weights.items()
    )


@deal.pre(
    lambda du_detsf, du_mf2to4, du_mf5p, du_attsf, emp, shares: np.all(du_detsf >= 0)
)
@deal.pre(
    lambda du_detsf, du_mf2to4, du_mf5p, du_attsf, emp, shares: np.all(du_mf2to4 >= 0)
)
@deal.pre(
    lambda du_detsf, du_mf2to4, du_mf5p, du_attsf, emp, shares: np.all(du_mf5p >= 0)
)
@deal.pre(
    lambda du_detsf, du_mf2to4, du_mf5p, du_attsf, emp, shares: np.all(du_attsf >= 0)
)
@deal.pre(lambda du_detsf, du_mf2to4, du_mf5p, du_attsf, emp, shares: np.all(emp >= 0))
@deal.post(lambda result: np.all(result[0] >= 0))  # trips_res
@deal.post(lambda result: np.all(result[1] >= 0))  # trips_school
@deal.post(lambda result: np.all(result[2] >= 0))  # trips_nonres
@deal.post(lambda result: np.all(result[3] >= 0))  # trips_total
@deal.post(lambda result: np.all(result[4] >= 0))  # trips_hbw
@deal.post(lambda result: np.all(result[5] >= 0))  # trips_hbo
@deal.post(lambda result: np.all(result[6] >= 0))  # trips_nhb
@deal.post(
    lambda result: np.all(
        (np.abs((result[4] + result[5] + result[6]) - result[3]) < 1e-6)
        | (result[3] == 0)
    )
)
def compute_trip_generation(
    du_detsf: np.ndarray,
    du_mf2to4: np.ndarray,
    du_mf5p: np.ndarray,
    du_attsf: np.ndarray,
    emp: np.ndarray,
    sector_shares: Sequence[Mapping[str, float] | None],
    du_rate_detsf: float = 9.57,
    du_rate_mf2to4: float = 6.65,
    du_rate_mf5p: float = 4.18,
    school_share: float = 0.097,
    hbw_pct: float = 0.18,
    hbo_pct: float = 0.42,
    nhb_pct: float = 0.40,
) -> tuple[np.ndarray, ...]:
    """SQL: ``trip_generation`` — daily trips from activity, not floor area.

    Housing classes: ``du_detsf`` is detached (large- and small-lot together),
    ``du_mf2to4`` 2-4 units, ``du_mf5p`` 5+ units, ``du_attsf`` attached
    single-family. The reference implementation computes attached units and
    then omits them from trip generation entirely; the SQL prices them at the
    5+ rate instead of dropping them, so they are folded here too — that is the
    one deliberate deviation from the reference, and this is where it is pinned.

    Returns (trips_res, trips_school, trips_nonres, trips_total,
             trips_hbw, trips_hbo, trips_nhb).
    Post-condition: hbw + hbo + nhb ≈ total (trip purpose split).
    """
    trips_res = _c(du_detsf) * du_rate_detsf + _c(du_mf2to4) * du_rate_mf2to4
    trips_res = trips_res + (_c(du_mf5p) + _c(du_attsf)) * du_rate_mf5p
    trips_school = trips_res * school_share
    trips_nonres = np.array(
        [
            trip_employment(employment, shares)
            for employment, shares in zip(_c(emp), sector_shares, strict=True)
        ],
        dtype=float,
    )
    trips_total = trips_res + trips_school + trips_nonres
    trips_hbw = trips_total * hbw_pct
    trips_hbo = trips_total * hbo_pct
    trips_nhb = trips_total * nhb_pct
    return (
        trips_res,
        trips_school,
        trips_nonres,
        trips_total,
        trips_hbw,
        trips_hbo,
        trips_nhb,
    )


# ``internal_capture`` has no reference here: test_result_view_geometry.py drives
# the model directly, and the mirror this module used to carry had drifted (it
# measured external trips off trips_inbound, while the model measures them off
# trips_total — the QA the parity tests could not catch while they only ran the
# mirror against itself).
