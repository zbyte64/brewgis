"""Which Building Type a parcel should take — the preferences over the density bases.

Closest-matching is a density match, and density alone cannot tell two
archetypes apart that share a dwelling-unit rate but not a land use: a parcel
whose jobs are military employment is not the same parcel as one whose jobs are
office employment, yet both may sit at the same employment density. Two
*ranking preferences* sit on top of the density bases (``du``, ``emp``,
``built_form_key``) — never replacing them, and each falling back to the list
it was given when nothing matches:

1. **Employment sector** — a Building Type that declares jobs in the parcel's
   largest employment sector is preferred over one that does not. A parcel's
   own jobs are the most specific thing matching knows about it.
2. **Land development category** — a Building Type of the parcel's own
   :class:`~brewgis.workspace.built_forms.models.LandDevelopmentCategoryChoices`
   is preferred over one in a different category.

Sector first is what keeps a sector out of the reach of the coarser category: a
parcel whose jobs are in a sector only *non*-urban archetypes employ would
otherwise lose that match to the category narrowing before it was ever tried.
The category governs the parcels the sector cannot speak for — a residential
parcel has no jobs at all, so only its category and its density rank it.

Both are narrowing preferences: within whatever the previous step left, the
density basis still chooses. A parcel with no sector match keeps the full list;
a parcel with no category match keeps the sector-narrowed list.

The sector vocabulary is the base canvas's own
(:py:data:`~brewgis.workspace.services.base_canvas_schema.EMPLOYMENT_SECTORS`):
a parcel's jobs are read from its ``emp_<sector>`` columns and a Building Type
declares them under the same ``<sector>`` key in ``jobs_by_sector``.

:func:`dominant_employment_sector` and :func:`dominant_employment_sector_sql`
are the two implementations of the same rule — one for the paint surfaces,
which hold a parcel row in Python, and one for the base-canvas fill model,
which ranks candidates inside a ``LEFT JOIN LATERAL``. They must agree on the
tie-break (the alphabetically first sector), so a change to one is a change to
the other.
"""

# ruff: noqa: S608 — the SQL built here interpolates column names from
# EMPLOYMENT_SECTORS and table aliases the caller owns; no value is user input.

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from brewgis.workspace.services.base_canvas_schema import EMPLOYMENT_SECTORS

if TYPE_CHECKING:
    from collections.abc import Mapping
    from collections.abc import Sequence

    from brewgis.workspace.built_forms.models import BuildingType


def dominant_employment_sector(row: Mapping[str, Any]) -> str | None:
    """Return the sector *row* has the most jobs in, or ``None`` if it has none.

    ``row`` is a canvas row keyed by column name (``emp_military`` and friends).
    Ties go to the alphabetically first sector — the same tie-break
    :func:`dominant_employment_sector_sql` uses, so both surfaces pick the same
    sector for the same parcel. Missing columns and non-positive values are
    treated as no jobs.
    """
    best_sector: str | None = None
    best_jobs = 0.0
    for sector in sorted(EMPLOYMENT_SECTORS):
        jobs = float(row.get(f"emp_{sector}") or 0.0)
        if jobs > best_jobs:
            best_sector, best_jobs = sector, jobs
    return best_sector


def prefer_same_category(
    candidates: Sequence[BuildingType], category: str | None
) -> Sequence[BuildingType]:
    """Narrow *candidates* to the ones matching *category*, when any do.

    Returns *candidates* unchanged when *category* is empty or no candidate
    carries it, so a workspace whose Building Types have no category (or a
    parcel whose category no type covers) matches exactly as it did before the
    preference existed.
    """
    if not category:
        return candidates
    category = str(category).strip()
    if not category:
        return candidates
    same_category = [
        building_type
        for building_type in candidates
        if building_type.land_development_category == category
    ]
    return same_category or candidates


def prefer_same_sector(
    candidates: Sequence[BuildingType], sector: str | None
) -> Sequence[BuildingType]:
    """Narrow *candidates* to the ones declaring jobs in *sector*, when any do.

    A type "declares" a sector by holding a positive share of it in
    ``jobs_by_sector`` — the field is a share mix, so the size of the share is
    irrelevant here and only presence is tested. Falls back to *candidates*
    unchanged when *sector* is ``None`` or no candidate declares it.
    """
    if sector is None:
        return candidates
    same_sector = [
        building_type
        for building_type in candidates
        if float((building_type.jobs_by_sector or {}).get(sector) or 0.0) > 0.0
    ]
    return same_sector or candidates


def declared_sectors(building_type: BuildingType) -> dict[str, float]:
    """Return the canonical sectors *building_type* declares, and their shares.

    Keys outside :py:data:`EMPLOYMENT_SECTORS` are dropped: a type whose
    ``jobs_by_sector`` predates the sector vocabulary (``{"retail": 80}``)
    declares nothing a parcel's ``emp_<sector>`` columns can be compared with.
    """
    declared = building_type.jobs_by_sector or {}
    return {
        sector: float(declared[sector])
        for sector in EMPLOYMENT_SECTORS
        if sector in declared and float(declared[sector] or 0.0) > 0.0
    }


def dominant_employment_sector_sql(prefix: str) -> str:
    """Return SQL for the sector *prefix*'s row has the most jobs in.

    The SQL twin of :func:`dominant_employment_sector`: a scalar subquery over
    the row's ``emp_<sector>`` columns, ``prefix`` being the table alias with
    its dot (``"s."`` for the fill model's source). No row comes back when the
    row has no jobs at all, which makes the surrounding ``CASE`` fall through
    to the non-preferred branch.
    """
    values = ", ".join(
        f"('{sector}', COALESCE({prefix}emp_{sector}, 0))"
        for sector in EMPLOYMENT_SECTORS
    )
    return (
        f"(SELECT sector FROM (VALUES {values}) AS jobs(sector, jobs)"
        " WHERE jobs > 0 ORDER BY jobs DESC, sector LIMIT 1)"
    )


def sector_preference_sql(*, parcel_prefix: str, form_prefix: str) -> str:
    """Return SQL ranking *form_prefix* candidates by *parcel_prefix*'s sector.

    ``0`` for a Building Type declaring the parcel's dominant employment sector
    and ``1`` for every other row, to be used as the leading ``ORDER BY`` key
    (or part of one).

    The declaration is read with ``jsonb_each_text`` rather than the ``?`` and
    ``->>`` operators: SQLMesh re-renders those as ``json_extract_path_text``,
    which Postgres only defines for ``json``, so a jsonb argument fails the
    model at execution. A NULL ``jobs_by_sector`` — an export predating the
    column — yields no rows, so such a table keeps the unpreferred order
    instead of failing.
    """
    dominant = dominant_employment_sector_sql(parcel_prefix)
    return (
        "CASE WHEN EXISTS ("
        f"SELECT 1 FROM jsonb_each_text({form_prefix}jobs_by_sector)"
        " AS declared(sector, share)"
        f" WHERE declared.sector = {dominant}"
        " AND declared.share::float8 > 0)"
        " THEN 0 ELSE 1 END"
    )
