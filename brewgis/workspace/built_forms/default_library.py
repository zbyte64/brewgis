"""Default Building Type library — the built forms every workspace starts with.

Every workspace ends up with the same 96-type library: added at creation
(``brewgis.workspace.views.workspace_create``) and, for a workspace that already
existed when this library landed, by migration
``0065_seed_default_built_forms``. It is a checked-in static fixture — nothing
here reads an external database at runtime.

Seeding *adds what a workspace is missing* rather than only filling an empty
catalogue: an entry whose name the workspace already holds is skipped, so
nothing existing is ever rewritten, and the workspaces that predate the library
— which hold the 15 generic archetypes below and so could never reach any of
the SACOG or farm-land types — gain the rest of it. Building Types a workspace
holds under a library name are re-aligned to that entry by
:func:`backfill_library_fields`, which is what keeps them eligible for
same-category and same-sector matching.

An entry describes only what its land use actually is. A type with no dwellings
(``du_per_acre`` of 0 or none — an office, a warehouse, a parking structure, a
crop type) carries no ``household_size`` and no ``vacancy_rate``: it has no
households to count, and the models that read those columns already fall back
to their own defaults when they are null. Only a type that houses people states
how many live in a unit.

Each entry may also carry a ``jobs_by_sector`` share mix, keyed by the base
canvas's employment sectors
(:py:data:`~brewgis.workspace.services.base_canvas_schema.EMPLOYMENT_SECTORS`) —
the same keys as the ``emp_<sector>`` columns, which is what lets matching
compare a Building Type against a parcel's own jobs. The SACOG entries derive
theirs from the translation table's ``pct_*`` columns, whose twelve groups are
coarser than the parcel's seventeen sectors. A group's share counts only when
it is *material* (at least 15% of the type's jobs — below that it is a residual
of the coarse grouping, not a statement that the type employs that sector), and
a material group is spread evenly across that group's own sectors, so a
construction- or arts-dominated parcel still finds an archetype that employs
it. Four rows take a sector whole instead, because their own label names one
the ``pct_*`` groups cannot express: Military, Hotel (accommodation), Airport
(transport/warehousing) and Agriculture. A row that is not an employment
composition at all declares none — a parking structure's handful of jobs are
attendants, and no sector in the vocabulary is one. The crop types are
``agriculture`` throughout. See
:mod:`brewgis.workspace.built_forms.matching` for what matching does with it.

Provenance (authoring time only, from the restored UrbanFootprint SACOG source
dump, ``planning/urbanfootprint-sacog-source-db.sql.gz``):

- **15 generic archetypes** — the hand-authored baseline that previously lived
  in the (now deleted) ``fixtures/default_library.json``, kept verbatim.
- **48 SACOG land-use types** — from the 49 rows of
  ``sacog_land_use_translation_table``. ``du_per_acre`` is the mid-point of the
  row's ``min_du_ac``/``max_du_ac`` band (0 when both are 0), ``emp_per_acre``
  is its ``max_emp_ac``. Two rows from that table are not library entries: its
  ``Civic/Institution`` row duplicates the generic ``Civic / Institutional``
  archetype, and its ``Light Industrial`` row is renamed to
  ``Light Industrial (SACOG)`` because that label is identical to the generic
  archetype's and a workspace may not hold two Building Types under one name
  (``uq_building_type_workspace_name``).
- **33 UrbanFootprint crop types** — one per row of ``croptypes``: farm land,
  which carries no residential or employment density at all.

``land_development_category`` uses the base canvas's parcel-level vocabulary
(:class:`~brewgis.workspace.built_forms.models.LandDevelopmentCategoryChoices`),
not the density vocabulary of
:func:`brewgis.sqlmesh.macros.geometry.classify_land_dev_category`. That choice
is deliberate: it makes the field directly comparable with the parcel column of
the same name, which closest-matching *requires* — a parcel is only ever
assigned a type naming its own category — see ``views.paint.run_match_built_form``
and ``sqlmesh/models/base_canvas/built_form_fill.py``. The ETL classifies a
parcel as ``urban``, ``industrial``, ``agricultural``, ``undeveloped`` or
SACOG's ``mixed_use`` (``services.base_canvas_pipeline._classify_land_use``),
and the last of those is no entry's category: a parcel category the library
cannot name is a library gap, not a licence to match across categories.
"""

# ruff: noqa: E501 — Building-Type descriptions are single-line phrases carried over from the source catalogs

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from typing import Any

from brewgis.workspace.built_forms.models import BuildingType
from brewgis.workspace.built_forms.models import LandDevelopmentCategoryChoices
from brewgis.workspace.built_forms.models import PlaceTypeBuildingTypeMix
from brewgis.workspace.models import PaintedCanvas

if TYPE_CHECKING:
    from brewgis.workspace.models import Workspace

_logger = logging.getLogger(__name__)

# Names this library used to define and does not define any more. The SACOG
# translation table's civic row duplicated the generic ``Civic / Institutional``
# archetype, so it was dropped from the library; a workspace seeded while it was
# still in the library holds its row.
RETIRED_LIBRARY_NAMES: frozenset[str] = frozenset({"Civic/Institution"})

# Catalog keys whose category is a non-residential fact — a lookup table for
# the derivation rule below, one set per rule so the rule stays reviewable.
_INDUSTRIAL_KEYS: frozenset[str] = frozenset(
    {
        "bt__heavy_industrial",
        "bt__light_industrial",
        "bt__light_industrialoffice",
        "bt__agricultural_processingretail_employment",
        "bt__airport_sacog",
    }
)
_CONSERVATION_KEYS: frozenset[str] = frozenset(
    {"bt__forest_sacog", "bt__water_sacog", "bt__park_andor_open_space_sacog"}
)
_UNDEVELOPED_KEYS: frozenset[str] = frozenset(
    {"bt__urban_reserve", "bt__blank_place_type", "bt__road_sacog"}
)
_CATEGORY_BY_KEY: dict[str, str] = {
    **dict.fromkeys(_INDUSTRIAL_KEYS, LandDevelopmentCategoryChoices.INDUSTRIAL),
    **dict.fromkeys(_CONSERVATION_KEYS, LandDevelopmentCategoryChoices.CONSERVATION),
    **dict.fromkeys(_UNDEVELOPED_KEYS, LandDevelopmentCategoryChoices.UNDEVELOPED),
}
_URBAN_DU_PER_ACRE = 12.0
_SUBURBAN_DU_PER_ACRE = 4.0


def derive_land_development_category(
    *,
    key: str,
    name: str,
    du_per_acre: float | None,
    emp_per_acre: float | None,  # noqa: ARG001 — the rule keys off du, not emp
    rural_flag: bool = False,
) -> str:
    """Return the land development category for one source catalog row.

    The rule this module's SACOG entries were generated with, kept here so the
    mapping from catalog facts to category is reviewable in one place. ``key``
    is the catalog's built-form key (``bt__*``/``ct__*``), ``name`` its label
    and ``du_per_acre``/``emp_per_acre`` its density band mid-point and
    employment density. Order matters — the first matching rule wins:

    1. a crop key, or SACOG's own Agriculture row → ``agricultural``
    2. the catalog's rural flag → ``rural``
    3. an "industrial" label, or a known industrial key → ``industrial``
    4. a known conservation key → ``conservation``
    5. a known unbuilt key (road, blank, urban reserve) → ``undeveloped``
    6. residential density → ``urban`` at 12+ du/ac, ``suburban`` at 4+
    7. everything else (employment, civic, education, medical, hotel, parking,
       mixed use, military, university) → ``urban``
    """
    if key.startswith("ct__") or key == "bt__agriculture_sacog":
        return LandDevelopmentCategoryChoices.AGRICULTURAL
    if rural_flag:
        return LandDevelopmentCategoryChoices.RURAL
    if "industrial" in name.lower():
        return LandDevelopmentCategoryChoices.INDUSTRIAL
    keyed = _CATEGORY_BY_KEY.get(key)
    if keyed is not None:
        return keyed
    return _category_from_density(du_per_acre)


def _category_from_density(du_per_acre: float | None) -> str:
    """Return the category implied by a residential density; ``urban`` if none.

    Mid-band densities below the suburban threshold (farm homes, large-lot and
    very-low-density detached) are ``rural``; a row with no residential density
    at all is an employment, civic or education use and lands on ``urban``.
    """
    if du_per_acre is None or du_per_acre <= 0:
        return LandDevelopmentCategoryChoices.URBAN
    if du_per_acre >= _URBAN_DU_PER_ACRE:
        return LandDevelopmentCategoryChoices.URBAN
    if du_per_acre >= _SUBURBAN_DU_PER_ACRE:
        return LandDevelopmentCategoryChoices.SUBURBAN
    return LandDevelopmentCategoryChoices.RURAL


def retire_library_entries(workspace: Workspace) -> int:
    """Delete *workspace*'s Building Types under a name this library retired.

    A retired name is one the library used to define (and therefore seeded) and
    does not define any more — its row in a workspace is an artifact of that
    seed, not a profile anyone authored. It is deleted only when nothing points
    at it: a paint that named it, or a place-type mix built on it, would be
    broken by the delete, so such a row is kept and logged instead. The
    workspace's own profiles are unaffected — they are never library names.
    Returns the number of rows deleted.
    """
    deleted = 0
    for building_type in BuildingType.objects.filter(
        workspace=workspace, name__in=RETIRED_LIBRARY_NAMES
    ):
        painted = PaintedCanvas.objects.filter(
            scenario__workspace=workspace, painted_text_value=building_type.name
        ).exists()
        mixed = PlaceTypeBuildingTypeMix.objects.filter(
            building_type=building_type
        ).exists()
        if painted or mixed:
            _logger.warning(
                "Keeping retired Building Type %r in workspace %s: %s reference it",
                building_type.name,
                workspace.pk,
                "paints" if painted else "a place-type mix",
            )
            continue
        building_type.delete()
        deleted += 1
    return deleted


def seed_default_built_forms(workspace: Workspace) -> int:
    """Add the library's Building Types that *workspace* is missing.

    Returns the number of entries created. An entry is written only when the
    workspace holds no Building Type of that name: existing rows — the SACOG
    demo workspace's v1 ``FlatBuiltForm`` extraction, or anything hand-authored
    — are never modified, renamed or removed, so a second call adds nothing and
    the operation is idempotent. A workspace is therefore brought up to the
    full library rather than only a workspace with an empty catalogue being
    seeded, which is what a workspace carrying the 15 hand-authored archetypes
    the old ``fixtures/default_library.json`` held needs to gain the SACOG and
    farm-land types.

    ``create()`` rather than ``bulk_create()`` so ``auto_now_add`` timestamps
    are populated.
    """
    existing = set(
        BuildingType.objects.filter(workspace=workspace).values_list("name", flat=True)
    )
    created = 0
    for fields in DEFAULT_BUILDING_TYPES:
        if fields["name"] in existing:
            continue
        BuildingType.objects.create(workspace=workspace, **fields)
        created += 1
    return created


def backfill_library_fields(workspace: Workspace) -> int:
    """Bring *workspace*'s library-named Building Types back onto the library.

    A Building Type whose name matches a library entry *is* that entry, so every
    field the entry prescribes is aligned to it. Without that, a corrected or
    enriched library — a revised sector mix, a category, a household size a type
    should never have carried — would never reach the workspaces that already
    hold its entries, and those workspaces would keep matching and painting with
    profiles the library no longer prescribes. The workspace's *own* profiles are
    the rows whose names the library does not have; those are never touched, and
    a profile a user has customised under a library name is kept by renaming it.
    Returns the number of rows updated.
    """
    updated = 0
    for building_type in BuildingType.objects.filter(workspace=workspace):
        entry = _LIBRARY_BY_NAME.get(building_type.name)
        if entry is None:
            continue
        changed = [
            field
            for field, value in entry.items()
            if field != "name" and getattr(building_type, field) != value
        ]
        if not changed:
            continue
        for field in changed:
            setattr(building_type, field, entry[field])
        building_type.save(update_fields=[*changed, "updated_at"])
        updated += 1
    return updated


DEFAULT_BUILDING_TYPES: list[dict[str, Any]] = [
    {
        "name": "Single-Family Detached - Large Lot",
        "description": "Detached single-family homes on large lots (> 10,000 sqft). Typical of rural residential and estate subdivisions.",
        "du_per_acre": 2.0,
        "emp_per_acre": 0.0,
        "far": 0.3,
        "household_size": 2.8,
        "tenure_owner_pct": 90.0,
        "tenure_renter_pct": 10.0,
        "vacancy_rate": 3.0,
        "stories": 2,
        "footprint_per_unit": 150.0,
        "building_coverage": 15.0,
        "jobs_by_sector": {},
        "indoor_water_rate": 250.0,
        "outdoor_water_rate": 500.0,
        "irrigable_area_fraction": 0.3,
        "electricity_eui": 80.0,
        "gas_eui": 120.0,
        "vintage": "post_2000",
        "parking_spaces_per_unit": 2.0,
        "parking_spaces_per_1000sqft": 0.0,
        "parking_sqft_per_space": 300.0,
        "ite_land_use_code": 210,
        "trip_rate_override": 9.5,
        "pass_by_trip_pct": 0.0,
        "land_development_category": "rural",
    },
    {
        "name": "Single-Family Detached - Standard",
        "description": "Standard detached single-family homes on medium lots (5,000-10,000 sqft). Typical of post-war and modern subdivisions.",
        "du_per_acre": 5.0,
        "emp_per_acre": 0.0,
        "far": 0.45,
        "household_size": 2.6,
        "tenure_owner_pct": 85.0,
        "tenure_renter_pct": 15.0,
        "vacancy_rate": 4.0,
        "stories": 2,
        "footprint_per_unit": 120.0,
        "building_coverage": 25.0,
        "jobs_by_sector": {},
        "indoor_water_rate": 240.0,
        "outdoor_water_rate": 400.0,
        "irrigable_area_fraction": 0.25,
        "electricity_eui": 75.0,
        "gas_eui": 110.0,
        "vintage": "post_2000",
        "parking_spaces_per_unit": 2.0,
        "parking_spaces_per_1000sqft": 0.0,
        "parking_sqft_per_space": 300.0,
        "ite_land_use_code": 210,
        "trip_rate_override": 9.5,
        "pass_by_trip_pct": 0.0,
        "land_development_category": "suburban",
    },
    {
        "name": "Single-Family Attached (Townhouse)",
        "description": "Attached single-family homes in row configurations. Common in compact neighborhoods and infill development.",
        "du_per_acre": 12.0,
        "emp_per_acre": 0.0,
        "far": 0.7,
        "household_size": 2.4,
        "tenure_owner_pct": 70.0,
        "tenure_renter_pct": 30.0,
        "vacancy_rate": 5.0,
        "stories": 3,
        "footprint_per_unit": 80.0,
        "building_coverage": 40.0,
        "jobs_by_sector": {},
        "indoor_water_rate": 220.0,
        "outdoor_water_rate": 200.0,
        "irrigable_area_fraction": 0.15,
        "electricity_eui": 70.0,
        "gas_eui": 100.0,
        "vintage": "post_2000",
        "parking_spaces_per_unit": 1.5,
        "parking_spaces_per_1000sqft": 0.0,
        "parking_sqft_per_space": 300.0,
        "ite_land_use_code": 215,
        "trip_rate_override": 6.5,
        "pass_by_trip_pct": 0.0,
        "land_development_category": "urban",
    },
    {
        "name": "Duplex / Two-Flat",
        "description": "Two-unit residential buildings, often owner-occupied. Common in older urban neighborhoods and transition zones.",
        "du_per_acre": 18.0,
        "emp_per_acre": 0.0,
        "far": 0.9,
        "household_size": 2.3,
        "tenure_owner_pct": 50.0,
        "tenure_renter_pct": 50.0,
        "vacancy_rate": 5.0,
        "stories": 2,
        "footprint_per_unit": 130.0,
        "building_coverage": 50.0,
        "jobs_by_sector": {},
        "indoor_water_rate": 210.0,
        "outdoor_water_rate": 150.0,
        "irrigable_area_fraction": 0.1,
        "electricity_eui": 65.0,
        "gas_eui": 95.0,
        "vintage": "1970_2000",
        "parking_spaces_per_unit": 1.0,
        "parking_spaces_per_1000sqft": 0.0,
        "parking_sqft_per_space": 300.0,
        "ite_land_use_code": 220,
        "trip_rate_override": 5.5,
        "pass_by_trip_pct": 0.0,
        "land_development_category": "urban",
    },
    {
        "name": "Triplex / Fourplex",
        "description": "Small multi-unit buildings with 3-4 units. A common missing-middle housing type.",
        "du_per_acre": 30.0,
        "emp_per_acre": 0.0,
        "far": 1.2,
        "household_size": 2.2,
        "tenure_owner_pct": 30.0,
        "tenure_renter_pct": 70.0,
        "vacancy_rate": 6.0,
        "stories": 3,
        "footprint_per_unit": 90.0,
        "building_coverage": 55.0,
        "jobs_by_sector": {},
        "indoor_water_rate": 200.0,
        "outdoor_water_rate": 100.0,
        "irrigable_area_fraction": 0.08,
        "electricity_eui": 60.0,
        "gas_eui": 90.0,
        "vintage": "1970_2000",
        "parking_spaces_per_unit": 1.0,
        "parking_spaces_per_1000sqft": 0.0,
        "parking_sqft_per_space": 300.0,
        "ite_land_use_code": 220,
        "trip_rate_override": 4.5,
        "pass_by_trip_pct": 0.0,
        "land_development_category": "urban",
    },
    {
        "name": "Courtyard Apartment",
        "description": "Garden-style apartments arranged around a central courtyard. 2-3 stories with surface parking.",
        "du_per_acre": 25.0,
        "emp_per_acre": 0.0,
        "far": 0.8,
        "household_size": 2.0,
        "tenure_owner_pct": 10.0,
        "tenure_renter_pct": 90.0,
        "vacancy_rate": 7.0,
        "stories": 3,
        "footprint_per_unit": 60.0,
        "building_coverage": 30.0,
        "jobs_by_sector": {},
        "indoor_water_rate": 190.0,
        "outdoor_water_rate": 300.0,
        "irrigable_area_fraction": 0.2,
        "electricity_eui": 55.0,
        "gas_eui": 80.0,
        "vintage": "1970_2000",
        "parking_spaces_per_unit": 1.5,
        "parking_spaces_per_1000sqft": 0.0,
        "parking_sqft_per_space": 300.0,
        "ite_land_use_code": 221,
        "trip_rate_override": 5.0,
        "pass_by_trip_pct": 0.0,
        "land_development_category": "urban",
    },
    {
        "name": "Stacked Flats",
        "description": "Mid-density apartments in multi-story buildings. 3-4 stories, common in urban neighborhoods.",
        "du_per_acre": 45.0,
        "emp_per_acre": 0.0,
        "far": 1.5,
        "household_size": 1.8,
        "tenure_owner_pct": 20.0,
        "tenure_renter_pct": 80.0,
        "vacancy_rate": 7.0,
        "stories": 4,
        "footprint_per_unit": 55.0,
        "building_coverage": 40.0,
        "jobs_by_sector": {},
        "indoor_water_rate": 180.0,
        "outdoor_water_rate": 80.0,
        "irrigable_area_fraction": 0.05,
        "electricity_eui": 50.0,
        "gas_eui": 75.0,
        "vintage": "post_2000",
        "parking_spaces_per_unit": 1.0,
        "parking_spaces_per_1000sqft": 0.0,
        "parking_sqft_per_space": 300.0,
        "ite_land_use_code": 222,
        "trip_rate_override": 4.0,
        "pass_by_trip_pct": 0.0,
        "land_development_category": "urban",
    },
    {
        "name": "Mid-Rise Apartment (5-9 Stories)",
        "description": "Multi-story apartment buildings with elevator access. Common along urban corridors and in downtown districts.",
        "du_per_acre": 80.0,
        "emp_per_acre": 0.0,
        "far": 3.0,
        "household_size": 1.7,
        "tenure_owner_pct": 30.0,
        "tenure_renter_pct": 70.0,
        "vacancy_rate": 6.0,
        "stories": 7,
        "footprint_per_unit": 45.0,
        "building_coverage": 50.0,
        "jobs_by_sector": {},
        "indoor_water_rate": 170.0,
        "outdoor_water_rate": 30.0,
        "irrigable_area_fraction": 0.03,
        "electricity_eui": 55.0,
        "gas_eui": 65.0,
        "vintage": "post_2000",
        "parking_spaces_per_unit": 0.8,
        "parking_spaces_per_1000sqft": 0.0,
        "parking_sqft_per_space": 300.0,
        "ite_land_use_code": 222,
        "trip_rate_override": 3.5,
        "pass_by_trip_pct": 0.0,
        "land_development_category": "urban",
    },
    {
        "name": "High-Rise Apartment (10+ Stories)",
        "description": "High-density residential towers. Common in downtown cores and dense urban centers.",
        "du_per_acre": 150.0,
        "emp_per_acre": 0.0,
        "far": 6.0,
        "household_size": 1.6,
        "tenure_owner_pct": 40.0,
        "tenure_renter_pct": 60.0,
        "vacancy_rate": 5.0,
        "stories": 20,
        "footprint_per_unit": 40.0,
        "building_coverage": 40.0,
        "jobs_by_sector": {},
        "indoor_water_rate": 160.0,
        "outdoor_water_rate": 10.0,
        "irrigable_area_fraction": 0.01,
        "electricity_eui": 60.0,
        "gas_eui": 55.0,
        "vintage": "new",
        "parking_spaces_per_unit": 0.5,
        "parking_spaces_per_1000sqft": 0.0,
        "parking_sqft_per_space": 300.0,
        "ite_land_use_code": 222,
        "trip_rate_override": 3.0,
        "pass_by_trip_pct": 0.0,
        "land_development_category": "urban",
    },
    {
        "name": "Neighborhood Retail",
        "description": "Small-scale retail and commercial serving local neighborhoods. Includes corner stores, cafes, and small shops.",
        "du_per_acre": None,
        "emp_per_acre": 25.0,
        "far": 0.5,
        "household_size": None,
        "tenure_owner_pct": None,
        "tenure_renter_pct": None,
        "vacancy_rate": None,
        "stories": 2,
        "footprint_per_unit": None,
        "building_coverage": 60.0,
        "jobs_by_sector": {"retail_services": 80.0, "restaurant": 20.0},
        "indoor_water_rate": None,
        "outdoor_water_rate": 200.0,
        "irrigable_area_fraction": 0.05,
        "electricity_eui": 120.0,
        "gas_eui": 80.0,
        "vintage": "post_2000",
        "parking_spaces_per_unit": None,
        "parking_spaces_per_1000sqft": 4.0,
        "parking_sqft_per_space": 300.0,
        "ite_land_use_code": 820,
        "trip_rate_override": None,
        "pass_by_trip_pct": 20.0,
        "land_development_category": "urban",
    },
    {
        "name": "General Commercial",
        "description": "Standard commercial development including strip malls, big-box retail, and services.",
        "du_per_acre": None,
        "emp_per_acre": 40.0,
        "far": 0.4,
        "household_size": None,
        "tenure_owner_pct": None,
        "tenure_renter_pct": None,
        "vacancy_rate": None,
        "stories": 1,
        "footprint_per_unit": None,
        "building_coverage": 40.0,
        "jobs_by_sector": {
            "retail_services": 60.0,
            "other_services": 25.0,
            "restaurant": 15.0,
        },
        "indoor_water_rate": None,
        "outdoor_water_rate": 300.0,
        "irrigable_area_fraction": 0.1,
        "electricity_eui": 150.0,
        "gas_eui": 100.0,
        "vintage": "post_2000",
        "parking_spaces_per_unit": None,
        "parking_spaces_per_1000sqft": 5.0,
        "parking_sqft_per_space": 300.0,
        "ite_land_use_code": 820,
        "trip_rate_override": None,
        "pass_by_trip_pct": 25.0,
        "land_development_category": "urban",
    },
    {
        "name": "Office - Low Rise",
        "description": "Low-rise office buildings (1-3 stories) in suburban office parks and business centers.",
        "du_per_acre": None,
        "emp_per_acre": 60.0,
        "far": 0.5,
        "household_size": None,
        "tenure_owner_pct": None,
        "tenure_renter_pct": None,
        "vacancy_rate": None,
        "stories": 2,
        "footprint_per_unit": None,
        "building_coverage": 25.0,
        "jobs_by_sector": {"office_services": 85.0, "other_services": 15.0},
        "indoor_water_rate": None,
        "outdoor_water_rate": 250.0,
        "irrigable_area_fraction": 0.2,
        "electricity_eui": 130.0,
        "gas_eui": 70.0,
        "vintage": "post_2000",
        "parking_spaces_per_unit": None,
        "parking_spaces_per_1000sqft": 4.0,
        "parking_sqft_per_space": 300.0,
        "ite_land_use_code": 710,
        "trip_rate_override": None,
        "pass_by_trip_pct": 5.0,
        "land_development_category": "urban",
    },
    {
        "name": "Office - Mid/High Rise",
        "description": "Multi-story office buildings in urban cores and downtowns. 5-20+ stories.",
        "du_per_acre": None,
        "emp_per_acre": 200.0,
        "far": 5.0,
        "household_size": None,
        "tenure_owner_pct": None,
        "tenure_renter_pct": None,
        "vacancy_rate": None,
        "stories": 15,
        "footprint_per_unit": None,
        "building_coverage": 45.0,
        "jobs_by_sector": {"office_services": 100.0},
        "indoor_water_rate": None,
        "outdoor_water_rate": 20.0,
        "irrigable_area_fraction": 0.02,
        "electricity_eui": 160.0,
        "gas_eui": 60.0,
        "vintage": "new",
        "parking_spaces_per_unit": None,
        "parking_spaces_per_1000sqft": 2.0,
        "parking_sqft_per_space": 300.0,
        "ite_land_use_code": 710,
        "trip_rate_override": None,
        "pass_by_trip_pct": 3.0,
        "land_development_category": "urban",
    },
    {
        "name": "Light Industrial",
        "description": "Light industrial, warehousing, and flex space. Includes manufacturing, logistics, and R&D.",
        "du_per_acre": None,
        "emp_per_acre": 15.0,
        "far": 0.4,
        "household_size": None,
        "tenure_owner_pct": None,
        "tenure_renter_pct": None,
        "vacancy_rate": None,
        "stories": 1,
        "footprint_per_unit": None,
        "building_coverage": 50.0,
        "jobs_by_sector": {
            "manufacturing": 60.0,
            "wholesale": 25.0,
            "transport_warehousing": 15.0,
        },
        "indoor_water_rate": 50.0,
        "outdoor_water_rate": 100.0,
        "irrigable_area_fraction": 0.05,
        "electricity_eui": 80.0,
        "gas_eui": 60.0,
        "vintage": "1970_2000",
        "parking_spaces_per_unit": None,
        "parking_spaces_per_1000sqft": 2.0,
        "parking_sqft_per_space": 400.0,
        "ite_land_use_code": 130,
        "trip_rate_override": None,
        "pass_by_trip_pct": 5.0,
        "land_development_category": "industrial",
    },
    {
        "name": "Civic / Institutional",
        "description": "Public and institutional facilities including schools, libraries, community centers, government buildings, and places of worship.",
        "du_per_acre": None,
        "emp_per_acre": 20.0,
        "far": 0.5,
        "household_size": None,
        "tenure_owner_pct": None,
        "tenure_renter_pct": None,
        "vacancy_rate": None,
        "stories": 2,
        "footprint_per_unit": None,
        "building_coverage": 25.0,
        "jobs_by_sector": {
            "public_admin": 50.0,
            "education": 30.0,
            "other_services": 20.0,
        },
        "indoor_water_rate": 100.0,
        "outdoor_water_rate": 400.0,
        "irrigable_area_fraction": 0.3,
        "electricity_eui": 100.0,
        "gas_eui": 90.0,
        "vintage": "1970_2000",
        "parking_spaces_per_unit": None,
        "parking_spaces_per_1000sqft": 3.0,
        "parking_sqft_per_space": 300.0,
        "ite_land_use_code": 620,
        "trip_rate_override": None,
        "pass_by_trip_pct": 0.0,
        "land_development_category": "urban",
    },
    {
        "name": "Agricultural Processing/Retail Employment",
        "description": "",
        "du_per_acre": 0.0,
        "emp_per_acre": 7.0,
        "far": 0.3,
        "household_size": None,
        "vacancy_rate": None,
        "jobs_by_sector": {
            "retail_services": 26.9,
            "manufacturing": 12.7,
            "wholesale": 12.7,
            "transport_warehousing": 12.7,
            "utilities": 12.7,
            "construction": 12.7,
        },
        "land_development_category": "industrial",
    },
    {
        "name": "Blank Place Type",
        "description": "",
        "du_per_acre": 0.0,
        "emp_per_acre": 0.0,
        "far": 0.3,
        "household_size": None,
        "vacancy_rate": None,
        "jobs_by_sector": {},
        "land_development_category": "undeveloped",
    },
    {
        "name": "CBD Office",
        "description": "",
        "du_per_acre": 0.0,
        "emp_per_acre": 711.0,
        "far": 0.3,
        "household_size": None,
        "vacancy_rate": None,
        "jobs_by_sector": {"office_services": 83.6},
        "land_development_category": "urban",
    },
    {
        "name": "Community/Neighborhood Commercial",
        "description": "",
        "du_per_acre": 0.0,
        "emp_per_acre": 28.0,
        "far": 0.3,
        "household_size": None,
        "vacancy_rate": None,
        "jobs_by_sector": {"retail_services": 50.0, "office_services": 44.4},
        "land_development_category": "urban",
    },
    {
        "name": "Community/Neighborhood Commercial/Office",
        "description": "",
        "du_per_acre": 0.0,
        "emp_per_acre": 37.0,
        "far": 0.3,
        "household_size": None,
        "vacancy_rate": None,
        "jobs_by_sector": {"office_services": 70.6, "retail_services": 26.5},
        "land_development_category": "urban",
    },
    {
        "name": "Community/Neighborhood Retail",
        "description": "",
        "du_per_acre": 0.0,
        "emp_per_acre": 20.0,
        "far": 0.3,
        "household_size": None,
        "vacancy_rate": None,
        "jobs_by_sector": {
            "restaurant": 33.0,
            "retail_services": 33.0,
            "other_services": 16.5,
            "arts_entertainment": 16.5,
        },
        "land_development_category": "urban",
    },
    {
        "name": "Farm Home",
        "description": "",
        "du_per_acre": 0.5,
        "emp_per_acre": 0.0,
        "far": 0.3,
        "household_size": 2.5,
        "vacancy_rate": 5.0,
        "jobs_by_sector": {},
        "land_development_category": "rural",
    },
    {
        "name": "Heavy Industrial",
        "description": "",
        "du_per_acre": 0.0,
        "emp_per_acre": 11.0,
        "far": 0.3,
        "household_size": None,
        "vacancy_rate": None,
        "jobs_by_sector": {
            "manufacturing": 20.0,
            "wholesale": 20.0,
            "transport_warehousing": 20.0,
            "utilities": 20.0,
            "construction": 20.0,
        },
        "land_development_category": "industrial",
    },
    {
        "name": "High Density Attached Residential",
        "description": "",
        "du_per_acre": 34.55,
        "emp_per_acre": 0.0,
        "far": 0.3,
        "household_size": 2.5,
        "vacancy_rate": 5.0,
        "jobs_by_sector": {},
        "land_development_category": "urban",
    },
    {
        "name": "High-Intensity Office",
        "description": "",
        "du_per_acre": 0.0,
        "emp_per_acre": 294.0,
        "far": 0.3,
        "household_size": None,
        "vacancy_rate": None,
        "jobs_by_sector": {"office_services": 63.9, "public_admin": 34.4},
        "land_development_category": "urban",
    },
    {
        "name": "LARGE LOT NOT FARM HOME",
        "description": "",
        "du_per_acre": 0.5,
        "emp_per_acre": 0.0,
        "far": 0.3,
        "household_size": 2.5,
        "vacancy_rate": 5.0,
        "jobs_by_sector": {},
        "land_development_category": "rural",
    },
    {
        "name": "K-12 School",
        "description": "",
        "du_per_acre": 0.0,
        "emp_per_acre": 20.0,
        "far": 0.3,
        "household_size": None,
        "vacancy_rate": None,
        "jobs_by_sector": {"education": 100.0},
        "land_development_category": "urban",
    },
    {
        "name": "Agriculture",
        "description": "",
        "du_per_acre": 0.0,
        "emp_per_acre": 0.0,
        "far": 0.3,
        "household_size": None,
        "vacancy_rate": None,
        "jobs_by_sector": {"agriculture": 100.0},
        "land_development_category": "agricultural",
    },
    {
        "name": "Regional Comercial/Office",
        "description": "",
        "du_per_acre": 0.0,
        "emp_per_acre": 50.0,
        "far": 0.3,
        "household_size": None,
        "vacancy_rate": None,
        "jobs_by_sector": {"retail_services": 54.0, "office_services": 40.0},
        "land_development_category": "urban",
    },
    {
        "name": "Light Industrial-Office",
        "description": "",
        "du_per_acre": 0.0,
        "emp_per_acre": 44.0,
        "far": 0.3,
        "household_size": None,
        "vacancy_rate": None,
        "jobs_by_sector": {"office_services": 85.0},
        "land_development_category": "industrial",
    },
    {
        "name": "Colleges and Universities",
        "description": "",
        "du_per_acre": 0.0,
        "emp_per_acre": 100.0,
        "far": 0.3,
        "household_size": None,
        "vacancy_rate": None,
        "jobs_by_sector": {"education": 100.0},
        "land_development_category": "urban",
    },
    {
        "name": "Mid-Rise Mixed Use",
        "description": "",
        "du_per_acre": 99.0,
        "emp_per_acre": 135.0,
        "far": 0.3,
        "household_size": 2.5,
        "vacancy_rate": 5.0,
        "jobs_by_sector": {},
        "land_development_category": "urban",
    },
    {
        "name": "High-Rise Mixed Use",
        "description": "",
        "du_per_acre": 172.0,
        "emp_per_acre": 268.0,
        "far": 0.3,
        "household_size": 2.5,
        "vacancy_rate": 5.0,
        "jobs_by_sector": {},
        "land_development_category": "urban",
    },
    {
        "name": "Forest",
        "description": "",
        "du_per_acre": 0.0,
        "emp_per_acre": 0.0,
        "far": 0.3,
        "household_size": None,
        "vacancy_rate": None,
        "jobs_by_sector": {},
        "land_development_category": "conservation",
    },
    {
        "name": "Hotel",
        "description": "",
        "du_per_acre": 0.0,
        "emp_per_acre": 150.0,
        "far": 0.3,
        "household_size": None,
        "vacancy_rate": None,
        "jobs_by_sector": {"accommodation": 100.0},
        "land_development_category": "urban",
    },
    {
        "name": "Low Density Detached Residential",
        "description": "",
        "du_per_acre": 6.05,
        "emp_per_acre": 0.0,
        "far": 0.3,
        "household_size": 2.5,
        "vacancy_rate": 5.0,
        "jobs_by_sector": {},
        "land_development_category": "suburban",
    },
    {
        "name": "Medical Facility",
        "description": "",
        "du_per_acre": 0.0,
        "emp_per_acre": 176.0,
        "far": 0.3,
        "household_size": None,
        "vacancy_rate": None,
        "jobs_by_sector": {"medical_services": 90.7},
        "land_development_category": "urban",
    },
    {
        "name": "Medium Density Attached Residential",
        "description": "",
        "du_per_acre": 10.05,
        "emp_per_acre": 0.0,
        "far": 0.3,
        "household_size": 2.5,
        "vacancy_rate": 5.0,
        "jobs_by_sector": {},
        "land_development_category": "suburban",
    },
    {
        "name": "Medium Density Detached Residential",
        "description": "",
        "du_per_acre": 10.05,
        "emp_per_acre": 0.0,
        "far": 0.3,
        "household_size": 2.5,
        "vacancy_rate": 5.0,
        "jobs_by_sector": {},
        "land_development_category": "suburban",
    },
    {
        "name": "Medium-High Density Attached Residential",
        "description": "",
        "du_per_acre": 18.55,
        "emp_per_acre": 0.0,
        "far": 0.3,
        "household_size": 2.5,
        "vacancy_rate": 5.0,
        "jobs_by_sector": {},
        "land_development_category": "urban",
    },
    {
        "name": "Medium-High Density Detached Residential",
        "description": "",
        "du_per_acre": 18.55,
        "emp_per_acre": 0.0,
        "far": 0.3,
        "household_size": 2.5,
        "vacancy_rate": 5.0,
        "jobs_by_sector": {},
        "land_development_category": "urban",
    },
    {
        "name": "Mobile Home Park",
        "description": "",
        "du_per_acre": 12.5,
        "emp_per_acre": 0.0,
        "far": 0.3,
        "household_size": 2.5,
        "vacancy_rate": 5.0,
        "jobs_by_sector": {},
        "land_development_category": "urban",
    },
    {
        "name": "Moderate-Intensity Office",
        "description": "",
        "du_per_acre": 0.0,
        "emp_per_acre": 180.0,
        "far": 0.3,
        "household_size": None,
        "vacancy_rate": None,
        "jobs_by_sector": {"office_services": 88.5},
        "land_development_category": "urban",
    },
    {
        "name": "Regional Retail",
        "description": "",
        "du_per_acre": 0.0,
        "emp_per_acre": 53.0,
        "far": 0.3,
        "household_size": None,
        "vacancy_rate": None,
        "jobs_by_sector": {"retail_services": 70.7},
        "land_development_category": "urban",
    },
    {
        "name": "Residential/Retail Mixed Use High",
        "description": "",
        "du_per_acre": 27.5,
        "emp_per_acre": 47.0,
        "far": 0.3,
        "household_size": 2.5,
        "vacancy_rate": 5.0,
        "jobs_by_sector": {
            "office_services": 37.5,
            "retail_services": 20.8,
            "restaurant": 20.6,
            "other_services": 10.4,
            "arts_entertainment": 10.4,
        },
        "land_development_category": "urban",
    },
    {
        "name": "Residential/Retail Mixed Use Low",
        "description": "",
        "du_per_acre": 13.0,
        "emp_per_acre": 75.0,
        "far": 0.3,
        "household_size": 2.5,
        "vacancy_rate": 5.0,
        "jobs_by_sector": {
            "office_services": 52.9,
            "restaurant": 15.7,
            "retail_services": 15.7,
            "other_services": 7.8,
            "arts_entertainment": 7.8,
        },
        "land_development_category": "urban",
    },
    {
        "name": "Military",
        "description": "",
        "du_per_acre": 0.0,
        "emp_per_acre": 0.3,
        "far": 0.3,
        "household_size": None,
        "vacancy_rate": None,
        "jobs_by_sector": {"military": 100.0},
        "land_development_category": "urban",
    },
    {
        "name": "Road",
        "description": "",
        "du_per_acre": 0.0,
        "emp_per_acre": 0.0,
        "far": 0.3,
        "household_size": None,
        "vacancy_rate": None,
        "jobs_by_sector": {},
        "land_development_category": "undeveloped",
    },
    {
        "name": "Parking Lot",
        "description": "",
        "du_per_acre": 0.0,
        "emp_per_acre": 0.0,
        "far": 0.3,
        "household_size": None,
        "vacancy_rate": None,
        "jobs_by_sector": {},
        "land_development_category": "urban",
    },
    {
        "name": "Parking Structure",
        "description": "",
        "du_per_acre": 0.0,
        "emp_per_acre": 2.4,
        "far": 0.3,
        "household_size": None,
        "vacancy_rate": None,
        "jobs_by_sector": {},
        "land_development_category": "urban",
    },
    {
        "name": "Park and/or Open Space",
        "description": "",
        "du_per_acre": 0.0,
        "emp_per_acre": 0.0,
        "far": 0.3,
        "household_size": None,
        "vacancy_rate": None,
        "jobs_by_sector": {},
        "land_development_category": "conservation",
    },
    {
        "name": "Public/Quasi-Public",
        "description": "",
        "du_per_acre": 0.0,
        "emp_per_acre": 20.0,
        "far": 0.3,
        "household_size": None,
        "vacancy_rate": None,
        "jobs_by_sector": {"public_admin": 100.0},
        "land_development_category": "urban",
    },
    {
        "name": "Urban Attached Residential",
        "description": "",
        "du_per_acre": 103.55,
        "emp_per_acre": 6.0,
        "far": 0.3,
        "household_size": 2.5,
        "vacancy_rate": 5.0,
        "jobs_by_sector": {
            "restaurant": 33.0,
            "retail_services": 33.0,
            "other_services": 16.5,
            "arts_entertainment": 16.5,
        },
        "land_development_category": "urban",
    },
    {
        "name": "Urban Reserve",
        "description": "",
        "du_per_acre": 0.0,
        "emp_per_acre": 0.0,
        "far": 0.3,
        "household_size": None,
        "vacancy_rate": None,
        "jobs_by_sector": {},
        "land_development_category": "undeveloped",
    },
    {
        "name": "Very High Density Attached Residential",
        "description": "",
        "du_per_acre": 63.05,
        "emp_per_acre": 0.0,
        "far": 0.3,
        "household_size": 2.5,
        "vacancy_rate": 5.0,
        "jobs_by_sector": {},
        "land_development_category": "urban",
    },
    {
        "name": "Very Low Density Detached Residential",
        "description": "",
        "du_per_acre": 2.55,
        "emp_per_acre": 0.0,
        "far": 0.3,
        "household_size": 2.5,
        "vacancy_rate": 5.0,
        "jobs_by_sector": {},
        "land_development_category": "rural",
    },
    {
        "name": "Water",
        "description": "",
        "du_per_acre": 0.0,
        "emp_per_acre": 0.0,
        "far": 0.3,
        "household_size": None,
        "vacancy_rate": None,
        "jobs_by_sector": {},
        "land_development_category": "conservation",
    },
    {
        "name": "Airport",
        "description": "",
        "du_per_acre": 0.0,
        "emp_per_acre": 2.0,
        "far": 0.3,
        "household_size": None,
        "vacancy_rate": None,
        "jobs_by_sector": {"transport_warehousing": 100.0},
        "land_development_category": "industrial",
    },
    {
        "name": "Rural Residential",
        "description": "",
        "du_per_acre": 0.5,
        "emp_per_acre": 0.0,
        "far": 0.3,
        "household_size": 2.5,
        "vacancy_rate": 5.0,
        "jobs_by_sector": {},
        "land_development_category": "rural",
    },
    {
        "name": "Parking Structure w/Ground Floor Retail",
        "description": "",
        "du_per_acre": 0.0,
        "emp_per_acre": 41.5,
        "far": 0.3,
        "household_size": None,
        "vacancy_rate": None,
        "jobs_by_sector": {
            "restaurant": 33.0,
            "retail_services": 33.0,
            "other_services": 16.5,
            "arts_entertainment": 16.5,
        },
        "land_development_category": "urban",
    },
    {
        "name": "Urban Mid-Rise Residential",
        "description": "",
        "du_per_acre": 180.5,
        "emp_per_acre": 37.0,
        "far": 0.3,
        "household_size": 2.5,
        "vacancy_rate": 5.0,
        "jobs_by_sector": {},
        "land_development_category": "urban",
    },
    {
        "name": "Alfalfa",
        "description": "",
        "du_per_acre": 0.0,
        "emp_per_acre": 0.0,
        "far": 0.0,
        "household_size": None,
        "vacancy_rate": None,
        "jobs_by_sector": {"agriculture": 100.0},
        "land_development_category": "agricultural",
    },
    {
        "name": "Seed Rotation",
        "description": "",
        "du_per_acre": 0.0,
        "emp_per_acre": 0.0,
        "far": 0.0,
        "household_size": None,
        "vacancy_rate": None,
        "jobs_by_sector": {"agriculture": 100.0},
        "land_development_category": "agricultural",
    },
    {
        "name": "Safflower",
        "description": "",
        "du_per_acre": 0.0,
        "emp_per_acre": 0.0,
        "far": 0.0,
        "household_size": None,
        "vacancy_rate": None,
        "jobs_by_sector": {"agriculture": 100.0},
        "land_development_category": "agricultural",
    },
    {
        "name": "Almond",
        "description": "",
        "du_per_acre": 0.0,
        "emp_per_acre": 0.0,
        "far": 0.0,
        "household_size": None,
        "vacancy_rate": None,
        "jobs_by_sector": {"agriculture": 100.0},
        "land_development_category": "agricultural",
    },
    {
        "name": "Alfalfa Rotation",
        "description": "",
        "du_per_acre": 0.0,
        "emp_per_acre": 0.0,
        "far": 0.0,
        "household_size": None,
        "vacancy_rate": None,
        "jobs_by_sector": {"agriculture": 100.0},
        "land_development_category": "agricultural",
    },
    {
        "name": "Diversified Farm-Fruit Trees, Vegetables",
        "description": "",
        "du_per_acre": 0.0,
        "emp_per_acre": 0.0,
        "far": 0.0,
        "household_size": None,
        "vacancy_rate": None,
        "jobs_by_sector": {"agriculture": 100.0},
        "land_development_category": "agricultural",
    },
    {
        "name": "Rice Rotation",
        "description": "",
        "du_per_acre": 0.0,
        "emp_per_acre": 0.0,
        "far": 0.0,
        "household_size": None,
        "vacancy_rate": None,
        "jobs_by_sector": {"agriculture": 100.0},
        "land_development_category": "agricultural",
    },
    {
        "name": "Pasture",
        "description": "",
        "du_per_acre": 0.0,
        "emp_per_acre": 0.0,
        "far": 0.0,
        "household_size": None,
        "vacancy_rate": None,
        "jobs_by_sector": {"agriculture": 100.0},
        "land_development_category": "agricultural",
    },
    {
        "name": "Sorghum for/FOD",
        "description": "",
        "du_per_acre": 0.0,
        "emp_per_acre": 0.0,
        "far": 0.0,
        "household_size": None,
        "vacancy_rate": None,
        "jobs_by_sector": {"agriculture": 100.0},
        "land_development_category": "agricultural",
    },
    {
        "name": "Corn For/FOD",
        "description": "",
        "du_per_acre": 0.0,
        "emp_per_acre": 0.0,
        "far": 0.0,
        "household_size": None,
        "vacancy_rate": None,
        "jobs_by_sector": {"agriculture": 100.0},
        "land_development_category": "agricultural",
    },
    {
        "name": "CropType",
        "description": "",
        "du_per_acre": 0.0,
        "emp_per_acre": 0.0,
        "far": 0.0,
        "household_size": None,
        "vacancy_rate": None,
        "jobs_by_sector": {"agriculture": 100.0},
        "land_development_category": "agricultural",
    },
    {
        "name": "Blueberries",
        "description": "",
        "du_per_acre": 0.0,
        "emp_per_acre": 0.0,
        "far": 0.0,
        "household_size": None,
        "vacancy_rate": None,
        "jobs_by_sector": {"agriculture": 100.0},
        "land_development_category": "agricultural",
    },
    {
        "name": "Cherry",
        "description": "",
        "du_per_acre": 0.0,
        "emp_per_acre": 0.0,
        "far": 0.0,
        "household_size": None,
        "vacancy_rate": None,
        "jobs_by_sector": {"agriculture": 100.0},
        "land_development_category": "agricultural",
    },
    {
        "name": "Avocado",
        "description": "",
        "du_per_acre": 0.0,
        "emp_per_acre": 0.0,
        "far": 0.0,
        "household_size": None,
        "vacancy_rate": None,
        "jobs_by_sector": {"agriculture": 100.0},
        "land_development_category": "agricultural",
    },
    {
        "name": "Dried Bean",
        "description": "",
        "du_per_acre": 0.0,
        "emp_per_acre": 0.0,
        "far": 0.0,
        "household_size": None,
        "vacancy_rate": None,
        "jobs_by_sector": {"agriculture": 100.0},
        "land_development_category": "agricultural",
    },
    {
        "name": "Tomato Rotation",
        "description": "",
        "du_per_acre": 0.0,
        "emp_per_acre": 0.0,
        "far": 0.0,
        "household_size": None,
        "vacancy_rate": None,
        "jobs_by_sector": {"agriculture": 100.0},
        "land_development_category": "agricultural",
    },
    {
        "name": "Wheat",
        "description": "",
        "du_per_acre": 0.0,
        "emp_per_acre": 0.0,
        "far": 0.0,
        "household_size": None,
        "vacancy_rate": None,
        "jobs_by_sector": {"agriculture": 100.0},
        "land_development_category": "agricultural",
    },
    {
        "name": "Grape, Wine",
        "description": "",
        "du_per_acre": 0.0,
        "emp_per_acre": 0.0,
        "far": 0.0,
        "household_size": None,
        "vacancy_rate": None,
        "jobs_by_sector": {"agriculture": 100.0},
        "land_development_category": "agricultural",
    },
    {
        "name": "Blackberries",
        "description": "",
        "du_per_acre": 0.0,
        "emp_per_acre": 0.0,
        "far": 0.0,
        "household_size": None,
        "vacancy_rate": None,
        "jobs_by_sector": {"agriculture": 100.0},
        "land_development_category": "agricultural",
    },
    {
        "name": "Squash",
        "description": "",
        "du_per_acre": 0.0,
        "emp_per_acre": 0.0,
        "far": 0.0,
        "household_size": None,
        "vacancy_rate": None,
        "jobs_by_sector": {"agriculture": 100.0},
        "land_development_category": "agricultural",
    },
    {
        "name": "Walnuts",
        "description": "",
        "du_per_acre": 0.0,
        "emp_per_acre": 0.0,
        "far": 0.0,
        "household_size": None,
        "vacancy_rate": None,
        "jobs_by_sector": {"agriculture": 100.0},
        "land_development_category": "agricultural",
    },
    {
        "name": "Diversified Farm-Fruit Trees",
        "description": "",
        "du_per_acre": 0.0,
        "emp_per_acre": 0.0,
        "far": 0.0,
        "household_size": None,
        "vacancy_rate": None,
        "jobs_by_sector": {"agriculture": 100.0},
        "land_development_category": "agricultural",
    },
    {
        "name": "Prunes",
        "description": "",
        "du_per_acre": 0.0,
        "emp_per_acre": 0.0,
        "far": 0.0,
        "household_size": None,
        "vacancy_rate": None,
        "jobs_by_sector": {"agriculture": 100.0},
        "land_development_category": "agricultural",
    },
    {
        "name": "Broccoli",
        "description": "",
        "du_per_acre": 0.0,
        "emp_per_acre": 0.0,
        "far": 0.0,
        "household_size": None,
        "vacancy_rate": None,
        "jobs_by_sector": {"agriculture": 100.0},
        "land_development_category": "agricultural",
    },
    {
        "name": "Uncultivated Ag",
        "description": "",
        "du_per_acre": 0.0,
        "emp_per_acre": 0.0,
        "far": 0.0,
        "household_size": None,
        "vacancy_rate": None,
        "jobs_by_sector": {"agriculture": 100.0},
        "land_development_category": "agricultural",
    },
    {
        "name": "Asparagus",
        "description": "",
        "du_per_acre": 0.0,
        "emp_per_acre": 0.0,
        "far": 0.0,
        "household_size": None,
        "vacancy_rate": None,
        "jobs_by_sector": {"agriculture": 100.0},
        "land_development_category": "agricultural",
    },
    {
        "name": "Uncultivated Non-Ag",
        "description": "",
        "du_per_acre": 0.0,
        "emp_per_acre": 0.0,
        "far": 0.0,
        "household_size": None,
        "vacancy_rate": None,
        "jobs_by_sector": {"agriculture": 100.0},
        "land_development_category": "agricultural",
    },
    {
        "name": "Rangeland",
        "description": "",
        "du_per_acre": 0.0,
        "emp_per_acre": 0.0,
        "far": 0.0,
        "household_size": None,
        "vacancy_rate": None,
        "jobs_by_sector": {"agriculture": 100.0},
        "land_development_category": "agricultural",
    },
    {
        "name": "No Data",
        "description": "",
        "du_per_acre": 0.0,
        "emp_per_acre": 0.0,
        "far": 0.0,
        "household_size": None,
        "vacancy_rate": None,
        "jobs_by_sector": {"agriculture": 100.0},
        "land_development_category": "agricultural",
    },
    {
        "name": "Oats for/FOD",
        "description": "",
        "du_per_acre": 0.0,
        "emp_per_acre": 0.0,
        "far": 0.0,
        "household_size": None,
        "vacancy_rate": None,
        "jobs_by_sector": {"agriculture": 100.0},
        "land_development_category": "agricultural",
    },
    {
        "name": "Fallow",
        "description": "",
        "du_per_acre": 0.0,
        "emp_per_acre": 0.0,
        "far": 0.0,
        "household_size": None,
        "vacancy_rate": None,
        "jobs_by_sector": {"agriculture": 100.0},
        "land_development_category": "agricultural",
    },
    {
        "name": "Diversified Farm-Vegetables",
        "description": "",
        "du_per_acre": 0.0,
        "emp_per_acre": 0.0,
        "far": 0.0,
        "household_size": None,
        "vacancy_rate": None,
        "jobs_by_sector": {"agriculture": 100.0},
        "land_development_category": "agricultural",
    },
    {
        "name": "Bean Dried",
        "description": "",
        "du_per_acre": 0.0,
        "emp_per_acre": 0.0,
        "far": 0.0,
        "household_size": None,
        "vacancy_rate": None,
        "jobs_by_sector": {"agriculture": 100.0},
        "land_development_category": "agricultural",
    },
]


# Library name → its entry. A Building Type a workspace already holds under one
# of these names is that same archetype, so it takes the entry's own category
# and sector mix (``backfill_library_fields``).
_LIBRARY_BY_NAME: dict[str, dict[str, Any]] = {
    entry["name"]: entry for entry in DEFAULT_BUILDING_TYPES
}
