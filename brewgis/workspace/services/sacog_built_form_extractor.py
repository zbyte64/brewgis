"""SACOG v1 built forms → BuildingType extraction.

Each built form the v1 canvas names is profiled from the SACOG release's own
built-type catalogue, ``public.sacog_building_types_may14`` — one ``BuildingType``
row per ``bt__…`` key, holding dwelling units per acre, jobs per acre, the
``gross_net_ratio`` they are carried at, the per-housing-class and
per-employment-sector densities, the floor area and the irrigated area. The
relationship is the key itself:

  parcel.built_form_key → sacog_building_types_may14.key → density/intensity values

Each resulting record is *named after that key*, so the analysis models' key join
resolves it — see :func:`extract_built_forms` and
:mod:`brewgis.workspace.services.built_form_keys` for why.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING
from typing import Any

from django.db import connection

from brewgis.workspace.built_forms.models import BuildingType
from brewgis.workspace.services.built_form_keys import normalize_built_form_key

if TYPE_CHECKING:
    from brewgis.workspace.models import Workspace

logger = logging.getLogger(__name__)

#: The catalogue's row class holding a parcel-level built form — the
#: ``PlacetypeComponent``/``Placetype`` rows describe place types, not parcels.
BUILT_FORM_TYPE = "BuildingType"


def extract_built_forms(workspace: Workspace) -> int:
    """Extract the v1 built forms into BuildingType records for *workspace*.

    Profiles every built form the v1 canvas names from the SACOG built-type
    catalogue, and creates one BuildingType per key, named after that key.

    Additive and idempotent: a key an existing Building Type already resolves to
    is skipped, so a second call adds nothing, and the default library a
    workspace already holds is never touched. A caller rebuilding the catalogue
    deletes the workspace's Building Types itself and re-seeds the library
    (``default_library.seed_default_built_forms``) — this function cannot do that
    for it, because deleting them *after* the seeding is what would leave the
    workspace holding the 29 v1 keys and none of the library.

    Returns the number of new records created.
    """
    created = 0
    # The names a canvas key already resolves to, so a v1 key that an existing
    # (library) Building Type answers for is not answered a second time: two
    # rows matching one canvas key would duplicate every parcel that carries it
    # in ``core_end_state``'s join — and double its population, trips and VMT.
    resolved = {
        normalize_built_form_key(name)
        for name in BuildingType.objects.filter(workspace=workspace).values_list(
            "name", flat=True
        )
    }
    for key, catalogue_name in _get_parcel_built_forms():
        normalized = normalize_built_form_key(key)
        if normalized in resolved:
            logger.info(
                "Skipping v1 built form %s: this workspace already holds a "
                "Building Type that key resolves to",
                key,
            )
            continue

        profile = _catalogue_profile(key)
        if profile is None:
            logger.warning(
                "public.sacog_building_types_may14 names no %s row for %s; "
                "using the default profile",
                BUILT_FORM_TYPE,
                key,
            )
            profile = _default_profile()

        # Named after the canvas key, not the catalogue's display name, because
        # the key is what a canvas row names its built form with and
        # ``services.built_form_keys`` is the rule that pairs the two —
        # lowercased, ETL prefix dropped, ``_``/``-`` read as spaces. A
        # catalogue name does not survive that rule ("Rural Residential (SACOG)"
        # normalizes to "rural residential (sacog)" where the canvas key gives
        # "rural residential sacog"), so 13 of the demo's 29 keys would be
        # matched by no form at all: every parcel keyed to one at zero
        # population, zero dwelling units and zero employment, and with them
        # zero trip generation and zero VMT.
        profile["name"] = key
        # The catalogue's own label is kept as the description, so the Built
        # Forms panel shows what the slug stands for.
        profile["description"] = (
            f"SACOG v1 built form {catalogue_name!r} ({key})."
            if catalogue_name
            else f"SACOG v1 built form {key}."
        )

        BuildingType.objects.create(workspace=workspace, **profile)
        resolved.add(normalized)
        created += 1

    logger.info("Created %d BuildingType records from v1 built form catalog", created)
    return created


def _get_parcel_built_forms() -> list[tuple[str, str | None]]:
    """Return ``(canvas_key, catalogue_name)`` for every built form the v1 canvas names.

    The canvas and the catalogue agree on the key (both spell the parcel's built
    form ``bt__…``), which is what makes the join the identity one — the
    catalogue's numeric ``built_form_id`` is its own id space and joins
    ``main_builtform`` only by coincidence of numbering, which is exactly the
    trap :func:`_catalogue_profile` documents.
    """
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT DISTINCT bc.built_form_key, c.name
            FROM public.elk_grove_base_canvas bc
            LEFT JOIN public.sacog_building_types_may14 c
                ON c.key = bc.built_form_key
            WHERE bc.built_form_key IS NOT NULL AND bc.built_form_key != ''
            ORDER BY bc.built_form_key
        """)
        return [(row[0], row[1]) for row in cursor.fetchall()]


def _catalogue_profile(key: str) -> dict[str, Any] | None:
    """The catalogue's profile for *key*, or ``None`` when it names none.

    One row per built form: ``public.sacog_building_types_may14`` is the SACOG
    release's own built-type catalogue — 50 ``BuildingType`` rows, one per key,
    densities in dwelling units and jobs per acre and ``gross_net_ratio`` the
    factor the two are carried at. It is keyed by the ``bt__…`` key the canvas
    uses.

    Not ``public.footprint_flatbuiltform``: its ``built_form_id`` does not
    number the same forms as ``main_builtform.id``, so the two join without
    error and without meaning — the row for ``bt__rural_residential_sacog``
    there is the component catalogue's "Very Small Lot 2500 (The Boulders,
    Seattle WA)", and reading it as a rural density produced 26.24 units/acre
    against the canvas's own 0.24.
    """
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
               FROM public.sacog_building_types_may14
               WHERE key = %s AND built_form_type = %s""",
            [key, BUILT_FORM_TYPE],
        )
        row = cursor.fetchone()

    if row is None:
        return None
    return _build_profile([float(value) if value is not None else 0.0 for value in row])


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
        "du_type": _derive_du_type(v),
        "jobs_by_sector": _build_jobs_by_sector(v),
        "indoor_water_rate": 200.0,
        "outdoor_water_rate": v[26] * 0.01 if v[26] > 0 else 300.0,
        "irrigable_area_fraction": 0.25,
        "building_coverage": min(coverage, 100.0),
        "electricity_eui": 70.0,
        "gas_eui": 100.0,
    }


def _derive_du_type(v: Sequence[float]) -> str:
    """The housing class the catalogue declares a density for.

    Indices follow :func:`_build_profile`. A built form declares exactly one
    non-zero dwelling-unit density column, which is the class its units belong
    to — and the class the residential trip rate is chosen by
    (``built_forms.trip_rates``). A form with no housing density gets ``""``.
    """
    for idx, du_type in (
        (3, "detsf_ll"),
        (4, "detsf_sl"),
        (5, "attsf"),
        (6, "mf2to4"),
        (7, "mf5p"),
    ):
        if v[idx] > 0:
            return du_type
    return ""


def _build_jobs_by_sector(v: Sequence[float]) -> dict[str, float]:
    """Map FlatBuiltForm density columns to employment-sector share percentages.

    ``BuildingType.jobs_by_sector`` holds percentage shares of ``emp_per_acre``
    — the trip model multiplies each by the parcel's jobs and normalizes over
    the sectors present (see ``built_forms.trip_rates.sector_jobs``). The
    catalogue's sector densities are jobs/acre, so each is divided by the form's
    total employment density: writing the densities themselves would make a
    form's trip rate scale with its size twice over.
    """
    emp_density = v[1]
    if emp_density <= 0:
        return {}
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
            jobs[name] = 100.0 * val / emp_density
    return jobs


def _default_profile() -> dict[str, Any]:
    """Return a sensible default BuildingType profile when no FlatBuiltForm data exists."""
    return {
        "description": "Default profile (no v1 FlatBuiltForm data)",
        "du_per_acre": 5.0,
        # 5 units/acre is the small-lot detached class (the library's
        # "Single-Family Detached - Standard" carries the same density). Left
        # blank, the trip model could not price this profile's units at all.
        "du_type": "detsf_sl",
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
