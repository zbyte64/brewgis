"""Seeded Building Type library as a SQLMesh built-forms table.

``brewgis.seeds.default_built_forms`` publishes the checked-in
``DEFAULT_BUILDING_TYPES`` library (``workspace/built_forms/default_library.py``)
in the shape ``workspace/analysis/data_export.py`` exports a workspace's own
Building Types as: one row per built form carrying its ``du_per_acre``,
``emp_per_acre`` and ``jobs_by_sector`` mix. It is the table the POI built-form
override joins, so a parcel overridden to a built form takes that form's
densities from the library rather than from a literal in a model.

``jobs_by_sector`` is normalized to sum to 100 over the sectors an entry
declares — the same normalization ``built_forms/trip_rates.sector_jobs``
documents for SACOG's coarse ``pct_*`` groups, whose residual belongs to the
sectors the entry does name. That is what lets a reader divide a share by 100
and get an exact fraction of ``emp_per_acre``.

Densities and rates an entry omits read as 0 here, matching the
``_NULLABLE_TO_ZERO`` COALESCE in ``analysis/data_export.py``; ``household_size``,
``vacancy_rate``, ``vintage``, ``du_type`` and ``ite_land_use_code`` stay null.

The library is imported inside ``execute``: ``default_library`` imports Django,
and SQLMesh imports this module while loading the project, before Django is
configured.
"""

# ruff: noqa: PLC0415 — the library imports Django models; see the module docstring.

from __future__ import annotations

import json
from collections.abc import Iterator  # noqa: TC003
from typing import TYPE_CHECKING
from typing import Any

import pandas as pd
from sqlmesh import model
from sqlmesh.core.model.definition import ModelKindName

if TYPE_CHECKING:
    from sqlmesh.core.context import ExecutionContext
    from sqlmesh.utils.date import TimeLike

# Column set and types mirror ``analysis/data_export.py`` BUILT_FORM_COLUMNS.
_COLUMNS: dict[str, str] = {
    "id": "int",
    "key": "text",
    "land_development_category": "text",
    "du_per_acre": "double",
    "emp_per_acre": "double",
    "far": "double",
    "household_size": "double",
    "vacancy_rate": "double",
    "jobs_by_sector": "json",
    "indoor_water_rate": "double",
    "outdoor_water_rate": "double",
    "irrigable_area_fraction": "double",
    "building_coverage": "double",
    "electricity_eui": "double",
    "gas_eui": "double",
    "vintage": "text",
    "du_type": "text",
    "ite_land_use_code": "int",
}

# Columns an entry may omit that a reader consumes as a number, so an absent
# value is 0 rather than null (data_export's _NULLABLE_TO_ZERO).
_ZERO_WHEN_ABSENT: tuple[str, ...] = (
    "du_per_acre",
    "emp_per_acre",
    "far",
    "indoor_water_rate",
    "outdoor_water_rate",
    "irrigable_area_fraction",
    "building_coverage",
    "electricity_eui",
    "gas_eui",
)

# Columns carried through as null when the entry does not state them.
_NULLABLE: tuple[str, ...] = (
    "household_size",
    "vacancy_rate",
    "vintage",
    "du_type",
    "ite_land_use_code",
)


def normalize_shares(shares: dict[str, Any] | None) -> dict[str, float]:
    """Return *shares* rescaled so the sectors the entry declares sum to 100.

    A share mix that is empty or sums to zero stays empty: an entry with no
    employment composition declares none, and a reader's division by the sector
    total has nothing to divide.
    """
    positive = {key: float(value) for key, value in (shares or {}).items() if value}
    total = sum(positive.values())
    if total <= 0:
        return {}
    return {key: value * 100.0 / total for key, value in positive.items()}


@model(
    "brewgis.seeds.default_built_forms",
    kind=ModelKindName.FULL,
    description=(
        "The checked-in DEFAULT_BUILDING_TYPES library as a built-forms table: one row"
        " per built form with its dwelling-unit and employment densities and its"
        " jobs_by_sector share mix, read by the POI built-form override."
    ),
    column_descriptions={
        "id": "Row index of the entry in the seeded library.",
        "key": "Built form key: the entry's name, the label a parcel's built_form_key carries.",
        "land_development_category": "Land development category of the built form (urban, rural, ...).",
        "du_per_acre": "Dwelling units per acre the built form implies.",
        "emp_per_acre": "Jobs per acre the built form implies.",
        "far": "Floor area ratio of the built form.",
        "household_size": "People per household for the built form, null when it houses nobody.",
        "vacancy_rate": "Housing vacancy rate of the built form, null when it houses nobody.",
        "jobs_by_sector": "Employment share mix keyed by sector, normalized to sum to 100.",
        "indoor_water_rate": "Indoor water use rate of the built form.",
        "outdoor_water_rate": "Outdoor water use rate of the built form.",
        "irrigable_area_fraction": "Share of the parcel the built form leaves irrigable.",
        "building_coverage": "Share of the parcel the built form covers with buildings.",
        "electricity_eui": "Electricity energy use intensity of the built form.",
        "gas_eui": "Gas energy use intensity of the built form.",
        "vintage": "Construction vintage of the built form, null when unstated.",
        "du_type": "Dwelling unit type key of the built form, empty when it houses nobody.",
        "ite_land_use_code": "ITE land use code of the built form, null when unstated.",
    },
    columns=_COLUMNS,
)
def execute(
    context: ExecutionContext,  # noqa: ARG001
    start: TimeLike,  # noqa: ARG001
    end: TimeLike,  # noqa: ARG001
    execution_time: TimeLike,  # noqa: ARG001
    **kwargs: Any,  # noqa: ARG001
) -> Iterator[pd.DataFrame]:
    """Emit one row per entry of the seeded Building Type library."""
    from brewgis.workspace.built_forms.default_library import DEFAULT_BUILDING_TYPES

    rows: list[dict[str, Any]] = []
    for index, entry in enumerate(DEFAULT_BUILDING_TYPES):
        row: dict[str, Any] = {
            "id": index,
            "key": entry["name"],
            "land_development_category": entry.get("land_development_category"),
            "jobs_by_sector": json.dumps(normalize_shares(entry.get("jobs_by_sector"))),
        }
        row.update({field: entry.get(field) or 0.0 for field in _ZERO_WHEN_ABSENT})
        row.update({field: entry.get(field) for field in _NULLABLE})
        rows.append(row)

    yield pd.DataFrame(rows, columns=list(_COLUMNS))
