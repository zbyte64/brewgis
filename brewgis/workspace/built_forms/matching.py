"""Which Building Type a parcel should take — one constraint and one preference.

Closest-matching is a density match, and density alone cannot tell two
archetypes apart that share a dwelling-unit rate but not a land use: a parcel
whose jobs are military employment is not the same parcel as one whose jobs are
office employment, yet both may sit at the same employment density. Two rules
sit on top of the density bases (``du``, ``emp``, ``built_form_key``) — never
replacing them:

1. **Land development category — a constraint.** When the parcel names a
   category (not NULL, not blank: the parcel column is the ETL's own
   classification of the land), the only eligible Building Types are the ones
   naming that same category. A type that names none is not eligible either —
   an unset category is not a wildcard — so a parcel whose category no
   Building Type declares matches nothing at all rather than falling out to a
   neighbouring category. A parcel that names no category is not constrained.
2. **Employment sector — a preference.** Within what is left, a Building Type
   that declares jobs in the parcel's largest employment sector is preferred
   over one that does not, falling back to the whole eligible set when no type
   declares it. A parcel's own jobs are the most specific thing matching knows
   about it, but a library may simply not model a sector: a parking
   structure's handful of jobs are attendants, and no sector in the vocabulary
   is one.

The category is a constraint because it is a claim about the land, not a
tiebreaker between two plausible archetypes: a rural parcel is no more an
urban office tower for having office jobs near it, and leaving the rule soft
is how a vacant or agricultural parcel came to be assigned an urban mixed-use
archetype whose density then filled it with dwelling units it does not have.
The sector stays a preference because it is a claim about the *building*, and
absent a sector match the density bases still know something useful.

The density basis then chooses within whatever the two left — a parcel with no
sector match keeps the full eligible set.

The sector vocabulary is the base canvas's own
(:py:data:`~brewgis.workspace.services.base_canvas_schema.EMPLOYMENT_SECTORS`):
a parcel's jobs are read from its ``emp_<sector>`` columns and a Building Type
declares them under the same ``<sector>`` key in ``jobs_by_sector``.

Each rule exists twice — once for the paint surfaces, which hold a parcel row
in Python, and once for the base-canvas fill model, which applies it inside a
``LEFT JOIN LATERAL``: :func:`require_same_category` /
:func:`category_requirement_sql` and :func:`dominant_employment_sector` /
:func:`dominant_employment_sector_sql` (with the ranking form
:func:`sector_preference_sql`). Each pair must agree — on the sector tie-break
(the alphabetically first sector), on what counts as a blank category, and on
whose category is compared with whose — so a change to one is a change to the
other.
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


def require_same_category(
    candidates: Sequence[BuildingType], category: str | None
) -> Sequence[BuildingType]:
    """Return the *candidates* naming *category*; all of them when it is unset.

    *category* is the parcel's own ``land_development_category``. A parcel that
    names no category — NULL, or blank — is not narrowed at all: there is
    nothing to match against. Any other category is a requirement, so the
    result holds only types naming it, a Building Type naming none is not
    among them, and the result is *empty* when the library declares no type in
    the parcel's category. An empty list is the answer, not a licence to fall
    back to a neighbouring category — the caller reports the parcel unmatched.
    """
    if not category:
        return candidates
    wanted = str(category).strip()
    if not wanted:
        return candidates
    return [
        building_type
        for building_type in candidates
        if str(building_type.land_development_category or "").strip() == wanted
    ]


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


def category_requirement_sql(*, parcel_prefix: str, form_prefix: str) -> str:
    """Return SQL admitting only *form_prefix* rows naming *parcel_prefix*'s category.

    The SQL twin of :func:`require_same_category`, written for a ``WHERE``
    clause: a parcel naming no category constrains nothing, any other parcel
    admits only the Building Types naming the same one, and a form side that
    names none fails the comparison — SQL's ``NULL`` is not a match, so the row
    is dropped. Strictness is the point; a blank category is not a wildcard.

    Both sides are compared ``btrim``ed, which is how the blank test agrees
    with the Python side's ``str.strip``: a category of spaces is no category.
    """
    parcel_category = f"btrim({parcel_prefix}land_development_category)"
    form_category = f"btrim({form_prefix}land_development_category)"
    return (
        f"({parcel_category} IS NULL OR {parcel_category} = ''"
        f" OR {form_category} = {parcel_category})"
    )


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
