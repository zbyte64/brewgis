"""Per-activity trip generation rates, lifted from UrbanFootprint-OG.

UrbanFootprint v1.5 generates daily trips from land-use **activity** — dwelling
units by housing class, jobs by employment sector — and never from floor area:

    planning/v1/urbanfootprint-og/footprint/main/models/analysis_module/
        vmt_module/vmt_raw_trip_generation.py

That file is the reference for every number and every category in this module.
Its shape is the reason this module has no "non-residential floor area" concept:
UF's canvas carries ``bldg_sqft_*`` columns, but the VMT module reads none of
them (they feed the energy and public-health modules instead). A parcel that
both houses and employs people simply emits both terms — UF never decides
"residential" or "non-residential" from a density being non-zero.

The rates, as UF writes them (file:line in the reference tree):

| activity | UF expression | rate |
|---|---|---|
| ``du_detsf`` | ``* 9.57`` | 9.57 / dwelling unit / day |
| ``du_mf2to4`` | ``* 6.65`` | 6.65 / dwelling unit / day |
| ``du_mf5p`` | ``* 4.18`` | 4.18 / dwelling unit / day |
| ``emp_retail`` | ``(emp / cJobConversionRate) * 42.94`` | 21.47 / job / day |
| ``emp_restaccom`` | ``(emp / 2.0) * 75.0`` | 37.5 / job / day |
| ``emp_arts_entertainment`` | ``(emp / 2.0) * 20.0`` | 10.0 / job / day |
| ``emp_office`` | ``* 3.32`` | 3.32 / job / day |
| ``emp_public`` | ``* 3.32`` | 3.32 / job / day |
| ``emp_industry`` | ``* 3.02`` | 3.02 / job / day |
| K-12 school | 9.7% of the residential term | derived, not a land use |

``cJobConversionRate`` (``vmt_model_constants.py:38``) is 2 jobs per 1000 sq ft,
which is how UF carries the ITE shopping-centre rate of 42.94 trips / 1000 sq ft
/ day into a per-job rate. A rate applied to *floor area* is therefore never
correct in this codebase: 42.94 belongs to retail activity, and only after the
job conversion.

Deviations from the reference, both deliberate:

- **Attached single-family.** UF computes ``du_attsf`` and then omits it from
  trip generation entirely — its purpose splits and residential total read only
  ``du_detsf``/``du_mf2to4``/``du_mf5p``. Attached single-family is ~4.6% of
  SACOG's dwelling units, so dropping it would be a silent undercount. It is
  mapped onto the ``mf5p`` rate, the class the SACOG built-form catalogue
  itself files attached density under.
- **Sector vocabulary.** UF's six employment buckets are built from its canvas
  columns; BrewGIS's ``BuildingType.jobs_by_sector`` carries sixteen SACOG
  sector names instead. :data:`EMPLOYMENT_TRIP_RATES` is keyed by those sixteen
  names, so the mapping is the membership of this dict, and UF's buckets appear
  as the repeated rates (retail = ``retail_services``/``other_services``, and so
  on). Values are percentage shares of ``emp_per_acre`` — see
  :func:`sector_jobs`.

This module deliberately imports nothing: the SQLMesh macros import it at plan
time, and ``module_registry`` turns its constants into the analysis parameters
the models read through ``@blueprint_var``.
"""

from __future__ import annotations

# (value, label) pairs for BuildingType.du_type. The values are SACOG's
# built-form density vocabulary (``sacog_building_types_may14`` carries exactly
# one non-zero column per form out of these five), which is finer than UF's
# three trip classes; RESIDENTIAL_TRIP_RATES folds them back together.
DU_TYPES: tuple[tuple[str, str], ...] = (
    ("detsf_ll", "Single-family detached, large lot"),
    ("detsf_sl", "Single-family detached, small lot"),
    ("attsf", "Attached single-family"),
    ("mf2to4", "Multifamily, 2-4 units"),
    ("mf5p", "Multifamily, 5+ units"),
)

DU_TYPE_VALUES: tuple[str, ...] = tuple(value for value, _ in DU_TYPES)

# UF's three housing classes, read off the du_type a built form declares.
# ``attsf`` is the deliberate deviation documented in the module docstring.
RESIDENTIAL_TRIP_RATES: dict[str, float] = {
    "detsf_ll": 9.57,
    "detsf_sl": 9.57,
    "attsf": 4.18,
    "mf2to4": 6.65,
    "mf5p": 4.18,
}

# Trips per job per day, keyed by BrewGIS's ``jobs_by_sector`` sector names.
EMPLOYMENT_TRIP_RATES: dict[str, float] = {
    "retail_services": 21.47,
    "other_services": 21.47,
    "restaurant": 37.5,
    "accommodation": 37.5,
    "arts_entertainment": 10.0,
    "office_services": 3.32,
    "medical_services": 3.32,
    "public_admin": 3.32,
    "education": 3.32,
    "manufacturing": 3.02,
    "wholesale": 3.02,
    "transport_warehousing": 3.02,
    "construction": 3.02,
    "utilities": 3.02,
    "agriculture": 3.02,
    "military": 3.02,
}

# A built form that employs people but declares no sector mix gets the
# traffic-generating extreme rather than a silent zero or a blended average.
UNATTRIBUTED_EMPLOYMENT_TRIP_RATE: float = EMPLOYMENT_TRIP_RATES["retail_services"]

# UF derives K-12 trips from the residential term rather than from a school
# land use (``raw_trips_k12``, vmt_raw_trip_generation.py:114-115).
SCHOOL_TRIP_SHARE: float = 0.097


def residential_trips(dwelling_units: float, du_type: str) -> float:
    """Daily trips generated by *dwelling_units* of housed class *du_type*.

    Returns 0.0 for a blank or unknown class: a built form with dwelling units
    and no class is a data error the trip model audits for, not a case to guess
    a rate for.
    """
    rate = RESIDENTIAL_TRIP_RATES.get(du_type)
    if rate is None:
        return 0.0
    return dwelling_units * rate


def sector_jobs(
    employment: float, jobs_by_sector: dict[str, float] | None
) -> dict[str, float]:
    """Split *employment* jobs across *jobs_by_sector*'s share percentages.

    ``jobs_by_sector`` holds percentage shares of ``emp_per_acre`` — not
    densities and not absolute counts — and they do not always sum to 100
    (SACOG's ``pct_*`` columns leave a residual for sectors it does not
    publish). The shares are normalized, so the residual lands on the sectors
    the built form does declare rather than on a rate for a sector nobody named.

    An empty or absent map yields ``{"__unattributed__": employment}``, which
    :func:`employment_trips` prices at :data:`UNATTRIBUTED_EMPLOYMENT_TRIP_RATE`.
    That is the "fall back to retail" case: jobs exist, the mix does not.
    """
    if employment <= 0:
        return {}
    shares = {k: float(v) for k, v in (jobs_by_sector or {}).items() if v}
    total = sum(shares.values())
    if not shares or total <= 0:
        return {"__unattributed__": employment}
    return {sector: employment * share / total for sector, share in shares.items()}


def employment_trips(
    employment: float, jobs_by_sector: dict[str, float] | None
) -> dict[str, float]:
    """Daily trips per employment sector for *employment* jobs.

    Keys are the sector names (or ``__unattributed__``); values are trips, so
    the sum is the parcel's non-residential trip generation.
    """
    return {
        sector: jobs
        * EMPLOYMENT_TRIP_RATES.get(sector, UNATTRIBUTED_EMPLOYMENT_TRIP_RATE)
        for sector, jobs in sector_jobs(employment, jobs_by_sector).items()
    }


def total_trips(
    dwelling_units: float,
    du_type: str,
    employment: float,
    jobs_by_sector: dict[str, float] | None,
) -> float:
    """Daily trips from both activity terms, plus the derived school trips.

    ``school`` is the share of the residential term UF attributes to K-12
    travel; it is driven by households rather than by a school land use.
    """
    residential = residential_trips(dwelling_units, du_type)
    return (
        residential
        + residential * SCHOOL_TRIP_SHARE
        + sum(employment_trips(employment, jobs_by_sector).values())
    )
