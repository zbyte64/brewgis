"""SACOG v1 FlatBuiltForm → BuildingType extraction.

Relationship chain:
  parcel.built_form_key → main_builtform.key → main_builtform.id
  → footprint_flatbuiltform.built_form_id → density/intensity values

We aggregate all PrimaryComponent rows for each built_form_id to produce
a composite BuildingType profile per key.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from django.db import connection

from brewgis.workspace.built_forms.models import BuildingType

logger = logging.getLogger(__name__)


def extract_built_forms(overwrite: bool = False) -> int:
    """Extract v1 FlatBuiltForm records into BuildingType records.

    Traces parcel built_form_key → main_builtform → footprint_flatbuiltform,
    aggregates PrimaryComponent density values, and creates BuildingType records.

    Returns the number of new records created.
    """
    if not overwrite and BuildingType.objects.exists():
        logger.info(
            "BuildingType records already exist (%d), skipping. Use overwrite=True to replace.",
            BuildingType.objects.count(),
        )
        return 0

    if overwrite:
        BuildingType.objects.all().delete()

    created = 0
    for key, bf_id, name in _get_parcel_built_form_keys():
        profile = _aggregate_built_form_profile(bf_id)
        if profile is None:
            logger.debug(
                "No FlatBuiltForm rows for built_form_id=%s (key=%s)", bf_id, key
            )
            profile = _default_profile()

        profile["name"] = name or key

        bt, was_created = BuildingType.objects.update_or_create(
            name=key,
            defaults=profile,
        )
        if was_created:
            created += 1

    logger.info("Created %d BuildingType records from v1 built form catalog", created)
    return created


def _get_parcel_built_form_keys() -> list[tuple[str, int | None, str | None]]:
    """Return (parcel_key, main_builtform_id, main_builtform_name) tuples.

    Joins the parcel table with main_builtform on built_form_key.
    """
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT DISTINCT bc.built_form_key, mf.id, mf.name
            FROM public.elk_grove_base_canvas bc
            LEFT JOIN public.main_builtform mf ON bc.built_form_key = mf.key
            WHERE bc.built_form_key IS NOT NULL AND bc.built_form_key != ''
            ORDER BY bc.built_form_key
        """)
        return [(r[0], r[1], r[2]) for r in cursor.fetchall()]


def _aggregate_built_form_profile(bf_id: int | None) -> dict[str, Any] | None:
    """Aggregate PrimaryComponent FlatBuiltForm rows for a built_form_id.

    Returns a dict of averaged density/intensity values, or None if no rows.
    """
    if bf_id is None:
        return None

    with connection.cursor() as cursor:
        cursor.execute(
            """SELECT
                dwelling_unit_density,
                employment_density,
                gross_net_ratio,
                single_family_large_lot_density,
                single_family_small_lot_density,
                attached_single_family_density,
                multifamily_2_to_4_density,
                multifamily_5_plus_density,
                retail_services_density,
                restaurant_density,
                arts_entertainment_density,
                accommodation_density,
                other_services_density,
                office_services_density,
                public_admin_density,
                education_services_density,
                medical_services_density,
                manufacturing_density,
                wholesale_density,
                transport_warehouse_density,
                construction_utilities_density,
                agriculture_density,
                extraction_density,
                armed_forces_density,
                intersection_density,
                building_sqft_total,
                residential_irrigated_square_feet,
                commercial_irrigated_square_feet
               FROM public.footprint_flatbuiltform
               WHERE built_form_id = %s AND built_form_type = ANY(%s)""",
            [bf_id, ["PrimaryComponent"]],
        )
        rows = cursor.fetchall()

    if not rows:
        return None

    # Average across all PrimaryComponents
    n = len(rows)
    summed = [0.0] * len(rows[0])
    for row in rows:
        for i, val in enumerate(row):
            if val is not None:
                summed[i] += float(val)

    avg = [s / n for s in summed]
    return _build_profile(avg)


def _build_profile(v: Sequence[float]) -> dict[str, Any]:
    """Build a BuildingType defaults dict from averaged density values.

    v[0]  = dwelling_unit_density
    v[1]  = employment_density
    v[2]  = gross_net_ratio
    v[3]  = single_family_large_lot_density
    v[4]  = single_family_small_lot_density
    v[5]  = attached_single_family_density
    v[6]  = multifamily_2_to_4_density
    v[7]  = multifamily_5_plus_density
    v[8..23] = employment sector densities
    v[24] = intersection_density
    v[25] = building_sqft_total
    v[26] = residential_irrigated_sqft
    v[27] = commercial_irrigated_sqft
    """
    gnr = v[2] if v[2] > 0 else 1.0
    du_density = v[0]
    emp_density = v[1]
    bldg_sqft = v[25]

    # Derive FAR from building_sqft_total
    if gnr > 0 and bldg_sqft > 0:
        far = bldg_sqft / 43560.0 / gnr
    else:
        far = 0.3

    # Building coverage from building_sqft_total
    if bldg_sqft > 0:
        coverage = bldg_sqft * 100.0 / 43560.0
    else:
        coverage = 25.0

    return {
        "description": "",
        "du_per_acre": du_density * gnr,
        "emp_per_acre": emp_density * gnr,
        "far": max(far, 0.1),
        "household_size": 2.5,
        "vacancy_rate": 5.0,
        "jobs_by_sector": _build_jobs_by_sector(v, gnr),
        "indoor_water_rate": 200.0,
        "outdoor_water_rate": v[26] * 0.01 if v[26] > 0 else 300.0,
        "irrigable_area_fraction": 0.25,
        "building_coverage": min(coverage, 100.0),
        "electricity_eui": 70.0,
        "gas_eui": 100.0,
    }


def _build_jobs_by_sector(v: Sequence[float], gnr: float) -> dict[str, float]:
    """Map FlatBuiltForm density columns to sector-based jobs dict."""
    sector_map: dict[str, int] = {
        "retail_services": 8,
        "restaurant": 9,
        "arts_entertainment": 10,
        "accommodation": 11,
        "other_services": 12,
        "office_services": 13,
        "public_admin": 14,
        "education": 15,
        "medical_services": 16,
        "manufacturing": 17,
        "wholesale": 18,
        "transport_warehousing": 19,
        "utilities": 20,
        "construction": 20,
        "agriculture": 21,
        "extraction": 22,
        "military": 23,
    }
    jobs = {}
    for name, idx in sector_map.items():
        val = v[idx] if idx < len(v) else 0.0
        if val > 0:
            jobs[name] = val * gnr
    return jobs


def _default_profile() -> dict[str, Any]:
    """Return a sensible default BuildingType profile when no FlatBuiltForm data exists."""
    return {
        "description": "Default profile (no v1 FlatBuiltForm data)",
        "du_per_acre": 5.0,
        "emp_per_acre": 0.0,
        "far": 0.3,
        "household_size": 2.5,
        "vacancy_rate": 5.0,
        "jobs_by_sector": {},
        "indoor_water_rate": 200.0,
        "outdoor_water_rate": 300.0,
        "irrigable_area_fraction": 0.25,
        "building_coverage": 25.0,
        "electricity_eui": 70.0,
        "gas_eui": 100.0,
    }
