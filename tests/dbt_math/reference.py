"""Pure Python reference implementations of dbt SQL model formulas.

Each function mirrors a dbt SQL model's SELECT expressions exactly.
Decorated with ``@deal.pre`` / ``@deal.post`` contracts that document
and enforce the mathematical invariants at runtime.

Contracts are enforced only when ``DEAL_ENABLED=1`` (``make test-deal``).
Otherwise they serve as executable documentation.

Naming convention: ``compute_<output>`` or ``compute_<model>_<output>``
matching the dbt model or macro name.

All functions are pure: no I/O, no mutations.  numpy arrays are assumed
to be non-None and have matching lengths (validated by contracts).
"""
# mypy: ignore-errors
# ruff: noqa: ANN201, ARG005, PLR0913, ERA001

from __future__ import annotations

import deal
import numpy as np


# ══════════════════════════════════════════════════════════════════════
#  Helper: safe coalesce
# ══════════════════════════════════════════════════════════════════════

def _c(arr: np.ndarray, default: float = 0.0) -> np.ndarray:
    """COALESCE equivalent: replace NaN with *default*.

    numpy NaN is the sentinel for "SQL NULL after COALESCE became 0.0".
    """
    return np.where(np.isnan(arr), default, arr)


# ══════════════════════════════════════════════════════════════════════
#  Fiscal — Property Tax  (fiscal_property_tax.sql)
# ══════════════════════════════════════════════════════════════════════

@deal.pre(lambda du, bsqt, res_val, nonres_val, rate: np.all(du >= 0))
@deal.pre(lambda du, bsqt, res_val, nonres_val, rate: np.all(bsqt >= 0))
@deal.pre(lambda du, bsqt, res_val, nonres_val, rate: rate > 0)
@deal.post(lambda result: np.all(result[0] >= 0))   # assessed_value_res
@deal.post(lambda result: np.all(result[1] >= 0))   # assessed_value_nonres
@deal.post(lambda result: np.all(result[2] >= 0))   # property_tax_revenue
def compute_property_tax(
    dwelling_units_total: np.ndarray,
    building_sqft_total: np.ndarray,
    res_assessed_value_per_du: float = 350000.0,
    nonres_assessed_value_per_sqft: float = 150.0,
    property_tax_rate: float = 1.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """SQL: ``fiscal_property_tax`` — property tax from assessed value.

    Returns (assessed_value_res, assessed_value_nonres, property_tax_revenue).
    """
    av_res = _c(dwelling_units_total * res_assessed_value_per_du)
    av_nonres = _c(building_sqft_total * nonres_assessed_value_per_sqft)
    revenue = _c((_c(dwelling_units_total * res_assessed_value_per_du)
                  + _c(building_sqft_total * nonres_assessed_value_per_sqft))
                 * property_tax_rate / 100.0)
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
@deal.post(lambda result: np.all(
    np.abs(result[3] - (result[0] + result[1] + result[2])) < 1e-6
))
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
@deal.post(lambda result: np.all(result[0] >= 0))       # impervious_sqft
@deal.post(lambda result: np.all(result[1] >= 0))       # impervious_acres
@deal.post(lambda result: np.all(result[2] >= 0))       # pervious_acres
@deal.post(lambda result: np.all(result[3] >= 0))       # impervious_pct
@deal.post(lambda result: result[3].shape == result[0].shape)
@deal.post(lambda result: np.all(
    np.abs(result[1] * 43560.0 - result[0]) < 1e-3      # impervious_acres * 43560 ≈ impervious_sqft
    | (result[1] == 0)
))
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
    parking = _c((_c(dwelling_units_total * parking_per_unit)
                  + _c(employment_total * parking_per_employee))
                 * parking_space_sqft)
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
#  VMT  (vmt.sql)
# ══════════════════════════════════════════════════════════════════════

@deal.pre(lambda auto, length, pop: np.all(auto >= 0))
@deal.pre(lambda auto, length, pop: np.all(length >= 0))
@deal.pre(lambda auto, length, pop: np.all(pop >= 0))
@deal.post(lambda result: np.all(result[0] >= 0))       # vmt_total
@deal.post(lambda result: np.all(result[1] >= 0))       # vmt_per_capita
@deal.post(lambda result: np.all(result[2] >= 0))       # avg_trip_length_mi
@deal.post(lambda result: np.all(
    (result[1] == 0)
    | (np.abs(result[1] * result[3] - result[0]) < 1e-6)  # per_capita * pop ≈ vmt_total
))
def compute_vmt(
    auto_trips: np.ndarray,
    avg_trip_length_km: np.ndarray,
    population: np.ndarray,
    circuity_factor: float = 1.2,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """SQL: ``vmt`` — vehicle miles traveled.

    Returns (vmt_total, vmt_per_capita, avg_trip_length_mi, auto_trips).
    """
    vmt = auto_trips * avg_trip_length_km * 0.621371 * circuity_factor
    vmt_per_cap = np.where(population > 0, vmt / population, 0.0)
    trip_len_mi = avg_trip_length_km * 0.621371
    return vmt, vmt_per_cap, trip_len_mi, auto_trips


# ══════════════════════════════════════════════════════════════════════
#  Transport GHG  (transport_ghg.sql)
# ══════════════════════════════════════════════════════════════════════

@deal.pre(lambda vmt, pop: np.all(vmt >= 0))
@deal.pre(lambda vmt, pop: np.all(pop >= 0))
@deal.post(lambda result: np.all(result[0] >= 0))       # co2e_total_kg
@deal.post(lambda result: np.all(result[1] >= 0))       # co2e_per_capita_kg
def compute_transport_ghg(
    vmt_total: np.ndarray,
    population: np.ndarray,
    co2_per_mile: float = 0.411,
    speed_adjust: bool = False,
) -> tuple[np.ndarray, np.ndarray]:
    """SQL: ``transport_ghg`` — CO₂e from VMT.

    Returns (co2e_total_kg, co2e_per_capita_kg).
    """
    factor = 1.15 if speed_adjust else 1.0
    co2e = vmt_total * co2_per_mile * factor
    co2e_pc = np.where(population > 0, co2e / population, 0.0)
    return co2e, co2e_pc


# ══════════════════════════════════════════════════════════════════════
#  Physical Activity  (physical_activity.sql)
# ══════════════════════════════════════════════════════════════════════

@deal.pre(lambda wk, bk, length, auto, transit: np.all(wk >= 0))
@deal.pre(lambda wk, bk, length, auto, transit: np.all(bk >= 0))
@deal.pre(lambda wk, bk, length, auto, transit: np.all(length >= 0))
@deal.pre(lambda wk, bk, length, auto, transit: np.all(auto >= 0))
@deal.pre(lambda wk, bk, length, auto, transit: np.all(transit >= 0))
@deal.post(lambda result: np.all(result[0] >= 0))       # walk_met_hours
@deal.post(lambda result: np.all(result[1] >= 0))       # bike_met_hours
@deal.post(lambda result: np.all(result[2] >= 0))       # total_met_hours
@deal.post(lambda result: np.all(result[5] >= 0))       # active_trip_share
@deal.post(lambda result: np.all(result[5] <= 1.0 + 1e-10))
@deal.post(lambda result: np.all(
    np.abs(result[2] - (result[0] + result[1])) < 1e-6
))
def compute_physical_activity(
    walk_trips: np.ndarray,
    bike_trips: np.ndarray,
    avg_trip_length_km: np.ndarray,
    auto_trips: np.ndarray,
    transit_trips: np.ndarray,
    walk_met: float = 3.5,
    bike_met: float = 6.0,
    walk_speed_kmh: float = 4.8,
    bike_speed_kmh: float = 16.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """SQL: ``physical_activity`` — MET-hours from active transport.

    Returns (walk_met_hours, bike_met_hours, total_met_hours,
             walk_trips, bike_trips, active_trip_share).
    """
    walk_met_h = _c(walk_trips * (avg_trip_length_km / walk_speed_kmh) * walk_met)
    bike_met_h = _c(bike_trips * (avg_trip_length_km / bike_speed_kmh) * bike_met)
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

@deal.pre(lambda du, bsqt, acres_dev, elec_eui, gas_eui: np.all(du >= 0))
@deal.pre(lambda du, bsqt, acres_dev, elec_eui, gas_eui: np.all(bsqt >= 0))
@deal.pre(lambda du, bsqt, acres_dev, elec_eui, gas_eui: np.all(acres_dev >= 0))
@deal.pre(lambda du, bsqt, acres_dev, elec_eui, gas_eui: np.all(elec_eui >= 0))
@deal.pre(lambda du, bsqt, acres_dev, elec_eui, gas_eui: np.all(gas_eui >= 0))
@deal.post(lambda result: np.all(result[0] >= 0))       # energy_electricity_res
@deal.post(lambda result: np.all(result[1] >= 0))       # energy_gas_res
@deal.post(lambda result: np.all(result[2] >= 0))       # energy_electricity_nonres
@deal.post(lambda result: np.all(result[3] >= 0))       # energy_gas_nonres
@deal.post(lambda result: np.all(result[4] >= 0))       # energy_total
@deal.post(lambda result: np.all(result[5] >= 0))       # energy_intensity
@deal.post(lambda result: np.all(
    np.abs(result[4] - (result[0] + result[1] + result[2] + result[3])) < 1e-6
))
def compute_energy_demand(
    dwelling_units_total: np.ndarray,
    building_sqft_total: np.ndarray,
    acres_developed: np.ndarray,
    electricity_eui: np.ndarray,
    gas_eui: np.ndarray,
    res_far_default: float = 0.5,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """SQL: ``energy_demand`` — kWh/year by fuel type.

    SQL formula simplification: when du > 0,
      res_electric = elec_eui * 0.092903 * acres_dev * 43560 * res_far
                   = elec_eui * acres_dev * 4046.86 * res_far
    When du == 0, the NULLIF(du, 0) produces NULL and COALESCE gives 0.

    Returns (elec_res, gas_res, elec_nonres, gas_nonres, total, intensity_kwh_per_sqft).
    """
    sqft_to_m2 = 0.092903
    acres_to_sqft = 43560.0
    factor = sqft_to_m2 * acres_to_sqft * res_far_default  # 2023.43

    res_elec = np.where(
        dwelling_units_total > 0,
        electricity_eui * acres_developed * factor,
        0.0,
    )
    res_gas = np.where(
        dwelling_units_total > 0,
        gas_eui * acres_developed * factor,
        0.0,
    )
    nonres_elec = _c(building_sqft_total * sqft_to_m2 * electricity_eui)
    nonres_gas = _c(building_sqft_total * sqft_to_m2 * gas_eui)

    total = _c(res_elec) + _c(res_gas) + nonres_elec + nonres_gas
    intensity = np.where(building_sqft_total > 0, total / building_sqft_total, 0.0)
    return res_elec, res_gas, nonres_elec, nonres_gas, total, intensity


# ══════════════════════════════════════════════════════════════════════
#  Water Demand  (water_demand.sql)
# ══════════════════════════════════════════════════════════════════════

@deal.pre(lambda hh, hh_size, indoor, emp, res_irr, com_irr, outdoor, pop:  # noqa: PLR0913
          np.all(hh >= 0))
@deal.pre(lambda hh, hh_size, indoor, emp, res_irr, com_irr, outdoor, pop:  # noqa: PLR0913
          np.all(emp >= 0))
@deal.pre(lambda hh, hh_size, indoor, emp, res_irr, com_irr, outdoor, pop:  # noqa: PLR0913
          np.all(pop >= 0))
@deal.post(lambda result: np.all(result[0] >= 0))       # water_demand_res_indoor
@deal.post(lambda result: np.all(result[1] >= 0))       # water_demand_res_outdoor
@deal.post(lambda result: np.all(result[2] >= 0))       # water_demand_nonres_indoor
@deal.post(lambda result: np.all(result[3] >= 0))       # water_demand_nonres_outdoor
@deal.post(lambda result: np.all(result[4] >= 0))       # water_demand_total
@deal.post(lambda result: np.all(result[5] >= 0))       # water_demand_per_unit
@deal.post(lambda result: np.all(
    np.abs(result[4] - (result[0] + result[1] + result[2] + result[3])) < 1e-6
))
def compute_water_demand(  # noqa: PLR0913
    households: np.ndarray,
    household_size: np.ndarray,
    indoor_water_rate: np.ndarray,
    employment_total: np.ndarray,
    res_irrigated_sqft: np.ndarray,
    com_irrigated_sqft: np.ndarray,
    outdoor_water_rate: np.ndarray,
    population: np.ndarray,
    nonres_indoor_water_rate: float = 50.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """SQL: ``water_demand`` — liters/year by category.

    Returns (res_indoor, res_outdoor, nonres_indoor, nonres_outdoor,
             total, per_unit).
    """
    res_in = _c(households) * _c(household_size) * _c(indoor_water_rate) * 365.0
    res_out = _c(res_irrigated_sqft) * 0.092903 * _c(outdoor_water_rate)
    nonres_in = _c(employment_total) * nonres_indoor_water_rate * 365.0
    nonres_out = _c(com_irrigated_sqft) * 0.092903 * _c(outdoor_water_rate)

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

@deal.pre(lambda e_res, e_nonres, g_res, g_nonres, w_total, pop:  # noqa: PLR0913
          np.all(e_res >= 0) & np.all(e_nonres >= 0))
@deal.pre(lambda e_res, e_nonres, g_res, g_nonres, w_total, pop:  # noqa: PLR0913
          np.all(g_res >= 0) & np.all(g_nonres >= 0))
@deal.pre(lambda e_res, e_nonres, g_res, g_nonres, w_total, pop:  # noqa: PLR0913
          np.all(w_total >= 0))
@deal.pre(lambda e_res, e_nonres, g_res, g_nonres, w_total, pop:  # noqa: PLR0913
          np.all(pop >= 0))
@deal.post(lambda result: np.all(result[0] >= 0))       # co2e_energy_total_kg
@deal.post(lambda result: np.all(result[1] >= 0))       # co2e_water_total_kg
@deal.post(lambda result: np.all(result[2] >= 0))       # co2e_total_kg
@deal.post(lambda result: np.all(result[3] >= 0))       # co2e_per_capita_kg
@deal.post(lambda result: np.all(
    np.abs(result[2] - (result[0] + result[1])) < 1e-6
))
def compute_building_water_ghg(  # noqa: PLR0913
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
        _c(water_demand_total) / 3785411.8
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
@deal.post(lambda result: np.all(result[0] >= 0))       # acres_cultivated
@deal.post(lambda result: np.all(result[1] >= 0))       # crop_yield_tons
@deal.post(lambda result: np.all(result[2] >= 0))       # market_value
@deal.post(lambda result: np.all(result[3] >= 0))       # production_cost
@deal.post(lambda result: np.all(
    np.abs(result[4] - (result[2] - result[3])) < 1e-6   # net_return = market - cost
    | (result[2] == 0) | (result[3] == 0)
))
@deal.post(lambda result: np.all(result[5] >= 0))       # water_consumption_af
@deal.post(lambda result: np.all(result[6] >= 0))       # labor_hours
@deal.post(lambda result: np.all(result[7] >= 0))       # truck_trips
def compute_agriculture(
    parcel_acres_agriculture: np.ndarray,
    acres_developed: np.ndarray,
    is_rural: np.ndarray,         # bool array: land_dev_category == 'rural'
    crop_yield_per_acre: float = 8.0,
    crop_market_price_per_ton: float = 200.0,
    crop_production_cost_per_acre: float = 800.0,
    crop_water_per_acre_af: float = 3.0,
    crop_labor_hours_per_acre: float = 15.0,
    crop_truck_trips_per_acre: float = 2.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray,
           np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """SQL: ``agriculture`` — crop yield, value, resource use.

    Returns (acres_cultivated, crop_yield_tons, market_value,
             production_cost, net_return, water_consumption_af,
             labor_hours, truck_trips).
    """
    ag = _c(parcel_acres_agriculture)
    dev = _c(acres_developed)
    rural = is_rural.astype(bool)
    cultivated = np.where(
        ag > 0, ag,
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

@deal.pre(lambda du, bsqt, override, pass_by: np.all(du >= 0))
@deal.pre(lambda du, bsqt, override, pass_by: np.all(bsqt >= 0))
@deal.pre(lambda du, bsqt, override, pass_by: np.all(override >= 0))
@deal.pre(lambda du, bsqt, override, pass_by: np.all(pass_by >= 0))
@deal.post(lambda result: np.all(result[0] >= 0))       # trips_res
@deal.post(lambda result: np.all(result[1] >= 0))       # trips_nonres
@deal.post(lambda result: np.all(result[2] >= 0))       # trips_total
@deal.post(lambda result: np.all(result[3] >= 0))       # trips_hbw
@deal.post(lambda result: np.all(result[4] >= 0))       # trips_hbo
@deal.post(lambda result: np.all(result[5] >= 0))       # trips_nhb
@deal.post(lambda result: np.all(
    np.abs((result[3] + result[4] + result[5])
            - result[2]) < 1e-6
    | (result[2] == 0)
))
def compute_trip_generation(
    dwelling_units_total: np.ndarray,
    building_sqft_total: np.ndarray,
    trip_rate_override: np.ndarray,   # 0 if no override (treated as 0)
    pass_by_trip_pct: np.ndarray,     # 0-1, always a COALESCE'd value
    nonres_rate: float = 42.94,
    hbw_pct: float = 0.18,
    hbo_pct: float = 0.42,
    nhb_pct: float = 0.40,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray,
           np.ndarray, np.ndarray]:
    """SQL: ``trip_generation`` — daily trips with pass-by reduction.

    Returns (trips_res, trips_nonres, trips_total,
             trips_hbw, trips_hbo, trips_nhb).
    Post-condition: hbw + hbo + nhb ≈ total (trip purpose split).
    """
    trips_res = _c(dwelling_units_total * trip_rate_override)
    trips_nonres_raw = _c((building_sqft_total / 1000.0) * nonres_rate)
    pb_adj = 1.0 - _c(pass_by_trip_pct)

    trips_nonres = trips_nonres_raw * pb_adj
    trips_total = trips_res + trips_nonres
    trips_hbw = trips_total * hbw_pct
    trips_hbo = trips_total * hbo_pct
    trips_nhb = trips_total * nhb_pct
    return trips_res, trips_nonres, trips_total, trips_hbw, trips_hbo, trips_nhb


# ══════════════════════════════════════════════════════════════════════
#  Internal Capture  (internal_capture.sql)
# ══════════════════════════════════════════════════════════════════════

@deal.pre(lambda out, inbound, intra, frac, length, radius:  # noqa: PLR0913
          np.all(out >= 0) & np.all(length >= 0))
@deal.pre(lambda out, inbound, intra, frac, length, radius:  # noqa: PLR0913
          np.all(intra >= 0) & np.all(inbound >= 0))
@deal.pre(lambda out, inbound, intra, frac, length, radius:  # noqa: PLR0913
          0 <= frac <= 1)
@deal.pre(lambda out, inbound, intra, frac, length, radius:  # noqa: PLR0913
          radius > 0)
@deal.post(lambda result: np.all(result[0] >= 0))       # trips_internal
@deal.post(lambda result: np.all(result[1] <= 1.0 + 1e-10))  # internal_capture_pct
@deal.post(lambda result: np.all(result[1] >= 0))
@deal.post(lambda result: np.all(result[2] >= 0))       # trips_external
@deal.post(lambda result: np.all(
    result[2] >= result[0] - 1e-10,                     # external ≥ internal - epsilon
))
def compute_internal_capture(
    trips_outbound: np.ndarray,
    trips_inbound: np.ndarray,
    trips_intra_parcel: np.ndarray,
    parcel_capture_fraction: float,
    avg_trip_length_km: np.ndarray,
    study_area_radius_km: float,
    intrazonal_friction: float = 0.15,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """SQL: ``internal_capture`` — trips staying within the study area.

    The capture fraction is computed at the study-area level (not per-parcel).
    For individual parcels we compute::

        internal_capture_pct = min(1.0, fraction * exp(-friction * length / radius))

    Returns (trips_internal, internal_capture_pct, trips_external).
    """
    capture_pct = np.where(
        avg_trip_length_km > 0,
        np.minimum(
            1.0,
            parcel_capture_fraction
            * np.exp(-intrazonal_friction * avg_trip_length_km / study_area_radius_km),
        ),
        1.0,  # zero trip length → all internal
    )
    trips_internal = trips_intra_parcel + trips_outbound * capture_pct
    trips_external = np.maximum(
        0, trips_inbound - trips_intra_parcel - (trips_outbound * capture_pct)
    )
    return trips_internal, capture_pct, trips_external
