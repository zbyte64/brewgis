"""Synthetic parcel generator - generates realistic test parcels for ETL tests.

Generates a GeoDataFrame of *N* synthetic parcels within a bounding box
using rectangular grid with jitter. Each parcel gets:
    - A valid POLYGON geometry (WGS84)
    - A land development classification (``land_development_category``)
    - Distributions of population, employment, dwelling units, building area

All summable columns have non-zero values on at least some parcels. The
output is compatible with the base canvas schema column names.
"""

from __future__ import annotations

import math
import random

import geopandas as gpd
import numpy as np
from shapely.geometry import Polygon

from brewgis.workspace.services.base_canvas_schema import BaseCanvasSchema

# Land development categories with probability weights
LAND_USE_CATEGORIES: list[tuple[str, float]] = [
    ("urban", 0.50),
    ("suburban", 0.20),
    ("rural_residential", 0.10),
    ("commercial", 0.05),
    ("industrial", 0.04),
    ("agricultural", 0.05),
    ("park", 0.03),
    ("vacant", 0.03),
]

_DEFAULT_RANDOM_SEED = 42


def _select_category(rng: random.Random) -> str:
    """Weighted random selection of land development category."""
    if not LAND_USE_CATEGORIES:
        return "urban"
    categories, weights = zip(*LAND_USE_CATEGORIES, strict=True)
    return rng.choices(categories, weights=weights, k=1)[0]


def _generate_parcel_geometry(
    x: float,
    y: float,
    size_deg: float,
    rng: random.Random,
) -> Polygon:
    """Generate a rectangular polygon centered at (x, y) with random jitter."""
    hw = size_deg / 2.0
    jx = rng.uniform(-hw * 0.3, hw * 0.3)
    jy = rng.uniform(-hw * 0.3, hw * 0.3)
    return Polygon(
        [
            (x - hw + jx, y - hw + jy),
            (x + hw + jx, y - hw + jy),
            (x + hw + jx, y + hw + jy),
            (x - hw + jx, y + hw + jy),
            (x - hw + jx, y - hw + jy),
        ]
    )


def _compute_du_subtypes(du: float, rng: random.Random) -> dict[str, float]:
    """Distribute *du* into dwelling unit sub-types."""
    if du <= 0:
        return {
            "du_detsf": 0.0,
            "du_detsf_sl": 0.0,
            "du_detsf_ll": 0.0,
            "du_attsf": 0.0,
            "du_mf": 0.0,
            "du_mf2to4": 0.0,
            "du_mf5p": 0.0,
        }
    du_detsf = du * rng.uniform(0.3, 0.6)
    detsf_sl = du_detsf * rng.uniform(0.3, 0.6)
    detsf_ll = du_detsf - detsf_sl
    du_attsf = du * rng.uniform(0.05, 0.15)
    du_mf = max(0.0, du - du_detsf - du_attsf)
    mf2to4 = du_mf * rng.uniform(0.2, 0.5)
    mf5p = du_mf - mf2to4
    return {
        "du_detsf": round(du_detsf, 1),
        "du_detsf_sl": round(detsf_sl, 1),
        "du_detsf_ll": round(detsf_ll, 1),
        "du_attsf": round(du_attsf, 1),
        "du_mf": round(du_mf, 1),
        "du_mf2to4": round(mf2to4, 1),
        "du_mf5p": round(mf5p, 1),
    }


def _compute_emp_subtypes(total_emp: float, rng: random.Random) -> dict[str, float]:
    """Distribute employment into sub-types."""
    if total_emp <= 0:
        return {
            "emp": 0.0,
            "emp_ret": 0.0,
            "emp_off": 0.0,
            "emp_pub": 0.0,
            "emp_ind": 0.0,
            "emp_ag": 0.0,
            "emp_military": 0.0,
        }
    emp_ret = total_emp * rng.uniform(0.1, 0.3)
    emp_off = total_emp * rng.uniform(0.2, 0.4)
    emp_pub = total_emp * rng.uniform(0.05, 0.15)
    emp_ind = total_emp * rng.uniform(0.1, 0.25)
    emp_ag = total_emp * rng.uniform(0.0, 0.05)
    emp_military = total_emp * rng.uniform(0.0, 0.01)
    return {
        "emp": round(total_emp, 1),
        "emp_ret": round(emp_ret, 1),
        "emp_off": round(emp_off, 1),
        "emp_pub": round(emp_pub, 1),
        "emp_ind": round(emp_ind, 1),
        "emp_ag": round(emp_ag, 1),
        "emp_military": round(emp_military, 1),
    }


def _compute_building_area(
    du_values: dict[str, float],
    emp_values: dict[str, float],
    area_acres: float,  # noqa: ARG001
    rng: random.Random,
) -> dict[str, float]:
    """Estimate building areas from dwelling units and employment."""
    bldg: dict[str, float] = {}

    # Residential building area: du * floor_area_per_unit
    du_to_sqft = rng.uniform(800, 2000)
    bldg["bldg_area_detsf_sl"] = round(du_values["du_detsf_sl"] * du_to_sqft * 0.8, 1)
    bldg["bldg_area_detsf_ll"] = round(du_values["du_detsf_ll"] * du_to_sqft * 1.2, 1)
    bldg["bldg_area_attsf"] = round(du_values["du_attsf"] * du_to_sqft * 0.9, 1)
    bldg["bldg_area_mf"] = round(du_values["du_mf"] * du_to_sqft * 0.7, 1)

    # Commercial building area: emp * floor_area_per_employee
    emp_to_sqft = rng.uniform(200, 500)
    emp = emp_values["emp"]
    if emp > 0:
        bldg["bldg_area_retail_services"] = round(
            emp_values["emp_ret"] * 0.4 * emp_to_sqft, 1
        )
        bldg["bldg_area_restaurant"] = round(
            emp_values["emp_ret"] * 0.2 * emp_to_sqft, 1
        )
        bldg["bldg_area_accommodation"] = round(
            emp_values["emp_ret"] * 0.1 * emp_to_sqft, 1
        )
        bldg["bldg_area_arts_entertainment"] = round(
            emp_values["emp_ret"] * 0.05 * emp_to_sqft, 1
        )
        bldg["bldg_area_other_services"] = round(
            emp_values["emp_ret"] * 0.05 * emp_to_sqft, 1
        )
        bldg["bldg_area_office_services"] = round(
            emp_values["emp_off"] * 0.6 * emp_to_sqft, 1
        )
        bldg["bldg_area_public_admin"] = round(
            emp_values["emp_pub"] * 0.5 * emp_to_sqft, 1
        )
        bldg["bldg_area_education"] = round(
            emp_values["emp_pub"] * 0.3 * emp_to_sqft, 1
        )
        bldg["bldg_area_medical_services"] = round(
            emp_values["emp_off"] * 0.2 * emp_to_sqft, 1
        )
        bldg["bldg_area_transport_warehousing"] = round(
            emp_values["emp_ind"] * 0.5 * emp_to_sqft, 1
        )
        bldg["bldg_area_wholesale"] = round(
            emp_values["emp_ind"] * 0.3 * emp_to_sqft, 1
        )
    else:
        for key in (
            "bldg_area_retail_services",
            "bldg_area_restaurant",
            "bldg_area_accommodation",
            "bldg_area_arts_entertainment",
            "bldg_area_other_services",
            "bldg_area_office_services",
            "bldg_area_public_admin",
            "bldg_area_education",
            "bldg_area_medical_services",
            "bldg_area_transport_warehousing",
            "bldg_area_wholesale",
        ):
            bldg[key] = 0.0

    return bldg


def generate_synthetic_parcels(
    n: int,
    seed: int = _DEFAULT_RANDOM_SEED,
) -> gpd.GeoDataFrame:
    """Generate *n* synthetic parcels as a GeoDataFrame.

    Parcels are distributed in a rough grid with jitter within
    ``(-122.5, 36.5)`` to ``(-121.5, 37.5)`` (approximate Fresno area).

    Returns a GeoDataFrame with all 77 base canvas columns, compatible
    with the ETL pipeline's target schema.
    """
    if n <= 0:
        return gpd.GeoDataFrame(
            {
                col: []
                for col in BaseCanvasSchema.COLUMN_NAMES
                if col not in ("id", "geometry")
            },
            geometry=[],
            crs="EPSG:4326",
        )

    rng = random.Random(seed)
    np_rng = np.random.default_rng(seed)

    # Bounding box (approximate Fresno, CA)
    min_x, max_x = -122.5, -121.5
    min_y, max_y = 36.5, 37.5
    cols = int(math.ceil(math.sqrt(n)))
    rows = int(math.ceil(n / cols))
    cell_w = (max_x - min_x) / cols
    cell_h = (max_y - min_y) / rows
    cell_area_deg = cell_w * cell_h

    geometries: list[Polygon] = []
    rows_data: list[dict] = []

    for i in range(n):
        col_idx = i % cols
        row_idx = i // cols
        cx = min_x + (col_idx + 0.5) * cell_w
        cy = min_y + (row_idx + 0.5) * cell_h

        size_deg = math.sqrt(cell_area_deg) * rng.uniform(0.5, 1.0)
        geom = _generate_parcel_geometry(cx, cy, size_deg, rng)
        geometries.append(geom)

        # Compute area in acres (approximate: 1 deg^2 ~ 111km * 111km ~ 12300 km^2)
        # For Fresno latitude (~36.8), 1 deg lon ~ 89 km, 1 deg lat ~ 111 km
        km2_per_deg2 = 89.0 * 111.0
        acres_per_km2 = 247.105
        area_gross = size_deg * size_deg * km2_per_deg2 * acres_per_km2
        area_gross = max(0.01, min(area_gross, 640.0))

        category = _select_category(rng)

        # Demographics: population ~ area * density
        density = np_rng.lognormal(mean=1.5, sigma=1.0) * 5  # persons/acre
        pop = round(area_gross * density, 1)
        hh = round(pop / rng.uniform(2.0, 3.5), 1)  # persons per household
        du = round(hh * rng.uniform(0.95, 1.05), 1)  # dwelling units ~ households
        pop_groupquarter = round(pop * rng.uniform(0, 0.02), 1)

        du_sub = _compute_du_subtypes(du, rng)

        # Employment
        emp_ratio = (
            rng.uniform(0.0, 0.6) if category == "urban" else rng.uniform(0.0, 0.3)
        )
        total_emp = round(pop * emp_ratio, 1)
        emp_sub = _compute_emp_subtypes(total_emp, rng)

        emp_details: dict[str, float] = {}
        if total_emp > 0:
            emp_details["emp_retail_services"] = round(emp_sub["emp_ret"] * 0.5, 1)
            emp_details["emp_restaurant"] = round(emp_sub["emp_ret"] * 0.3, 1)
            emp_details["emp_accommodation"] = round(emp_sub["emp_ret"] * 0.1, 1)
            emp_details["emp_arts_entertainment"] = round(emp_sub["emp_ret"] * 0.05, 1)
            emp_details["emp_other_services"] = round(emp_sub["emp_ret"] * 0.05, 1)
            emp_details["emp_office_services"] = round(emp_sub["emp_off"] * 0.5, 1)
            emp_details["emp_medical_services"] = round(emp_sub["emp_off"] * 0.3, 1)
            emp_details["emp_public_admin"] = round(emp_sub["emp_pub"] * 0.4, 1)
            emp_details["emp_education"] = round(emp_sub["emp_pub"] * 0.3, 1)
            emp_details["emp_manufacturing"] = round(emp_sub["emp_ind"] * 0.3, 1)
            emp_details["emp_wholesale"] = round(emp_sub["emp_ind"] * 0.2, 1)
            emp_details["emp_transport_warehousing"] = round(
                emp_sub["emp_ind"] * 0.2, 1
            )
            emp_details["emp_utilities"] = round(emp_sub["emp_ind"] * 0.1, 1)
            emp_details["emp_construction"] = round(emp_sub["emp_ind"] * 0.1, 1)
            emp_details["emp_agriculture"] = round(emp_sub["emp_ag"] * 0.6, 1)
            emp_details["emp_extraction"] = 0.0
        else:
            keys = (
                "emp_retail_services",
                "emp_restaurant",
                "emp_accommodation",
                "emp_arts_entertainment",
                "emp_other_services",
                "emp_office_services",
                "emp_medical_services",
                "emp_public_admin",
                "emp_education",
                "emp_manufacturing",
                "emp_wholesale",
                "emp_transport_warehousing",
                "emp_utilities",
                "emp_construction",
                "emp_agriculture",
                "emp_extraction",
            )
            emp_details.update((k, 0.0) for k in keys)

        area_subtypes = _compute_area_subtypes(area_gross, category, rng)
        bldg_area = _compute_building_area(
            du_sub, {**emp_sub, **emp_details}, area_gross, rng
        )
        irrigation = _compute_irrigation(area_gross, category, rng)

        row: dict = {
            "id_source": f"synthetic_{i}",
            "geometry_key": f"synth_{i}",
            "land_development_category": category,
            "built_form_key": None,
            "intersection_density": round(rng.uniform(0, 25), 2),
            "area_gross": round(area_gross, 4),
            "area_parcel": round(area_gross * 0.85, 4),
            "area_dev_condition": round(area_gross * 0.7, 4),
            "area_row": round(area_gross * 0.15, 4),
        }
        row.update(area_subtypes)
        row.update(
            {
                "pop": pop,
                "pop_groupquarter": pop_groupquarter,
                "hh": hh,
                "du": du,
            }
        )
        row.update(du_sub)
        row.update(emp_sub)
        row.update(emp_details)
        row.update(bldg_area)
        row.update(irrigation)

        rows_data.append(row)

    gdf = gpd.GeoDataFrame(rows_data, geometry=geometries, crs="EPSG:4326")
    # Sort columns to match base canvas schema order, preserve geometry
    schema_cols = [c for c in BaseCanvasSchema.COLUMN_NAMES if c not in ("id",)]
    existing = [c for c in schema_cols if c in gdf.columns]
    return gdf[existing]


def _compute_area_subtypes(
    area_gross: float,
    category: str,
    rng: random.Random,
) -> dict[str, float]:
    """Distribute area into use-specific subtypes."""
    result: dict[str, float] = {}
    if category in ("urban", "suburban"):
        res_frac = rng.uniform(0.3, 0.6)
        emp_frac = rng.uniform(0.1, 0.4)
    elif category == "commercial":
        res_frac = rng.uniform(0.0, 0.2)
        emp_frac = rng.uniform(0.5, 0.8)
    elif category == "industrial":
        res_frac = rng.uniform(0.0, 0.1)
        emp_frac = rng.uniform(0.6, 0.85)
    elif category == "agricultural":
        res_frac = rng.uniform(0.1, 0.3)
        emp_frac = rng.uniform(0.0, 0.1)
    else:
        res_frac = rng.uniform(0.0, 0.3)
        emp_frac = rng.uniform(0.0, 0.1)

    res_area = area_gross * res_frac
    emp_area = area_gross * emp_frac
    mixed_use = area_gross * rng.uniform(0.0, 0.05)
    no_use = max(0.0, area_gross - res_area - emp_area - mixed_use)

    result["area_parcel_res"] = round(res_area, 4)
    result["area_parcel_res_detsf"] = round(res_area * rng.uniform(0.4, 0.7), 4)
    result["area_parcel_res_detsf_sl"] = round(
        result["area_parcel_res_detsf"] * rng.uniform(0.3, 0.6), 4
    )
    result["area_parcel_res_detsf_ll"] = round(
        result["area_parcel_res_detsf"] - result["area_parcel_res_detsf_sl"],
        4,
    )
    result["area_parcel_res_attsf"] = round(res_area * rng.uniform(0.05, 0.15), 4)
    result["area_parcel_res_mf"] = round(res_area * rng.uniform(0.05, 0.2), 4)

    result["area_parcel_emp"] = round(emp_area, 4)
    result["area_parcel_emp_ret"] = round(emp_area * rng.uniform(0.1, 0.3), 4)
    result["area_parcel_emp_off"] = round(emp_area * rng.uniform(0.2, 0.4), 4)
    result["area_parcel_emp_pub"] = round(emp_area * rng.uniform(0.05, 0.15), 4)
    result["area_parcel_emp_ind"] = round(emp_area * rng.uniform(0.1, 0.3), 4)
    result["area_parcel_emp_ag"] = round(emp_area * rng.uniform(0.0, 0.05), 4)
    result["area_parcel_emp_military"] = 0.0
    result["area_parcel_mixed_use"] = round(mixed_use, 4)
    result["area_parcel_no_use"] = round(no_use, 4)

    return result


def _compute_irrigation(
    area_gross: float,
    category: str,
    rng: random.Random,
) -> dict[str, float]:
    """Estimate irrigated areas."""
    if category == "agricultural":
        res_irr = area_gross * rng.uniform(0.1, 0.3)
        com_irr = area_gross * rng.uniform(0.0, 0.05)
    elif category in ("urban", "suburban"):
        res_irr = area_gross * rng.uniform(0.1, 0.25)
        com_irr = area_gross * rng.uniform(0.05, 0.15)
    elif category in ("commercial", "industrial"):
        res_irr = area_gross * rng.uniform(0.0, 0.05)
        com_irr = area_gross * rng.uniform(0.1, 0.2)
    else:
        res_irr = area_gross * rng.uniform(0.0, 0.1)
        com_irr = area_gross * rng.uniform(0.0, 0.05)

    return {
        "residential_irrigated_area": round(res_irr, 4),
        "commercial_irrigated_area": round(com_irr, 4),
    }
