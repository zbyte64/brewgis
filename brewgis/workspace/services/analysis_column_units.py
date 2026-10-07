"""Display units for the columns SQLMesh models publish.

The map's hover tooltip and the feature-inspect panel suffix each value with
its unit (``24.73 acres``, ``1,240 kg/yr``). A base canvas column gets its unit
from :class:`~brewgis.workspace.services.base_canvas_schema.BaseCanvasSchema`;
a column that comes from a SQLMesh model — every analysis layer — gets it from
the model's own ``column_descriptions``, which is where this repository
documents what an output column holds, unit stated parenthetically:

    co2e_total = 'Transport plus building and water CO2e (kg per year).'

Only the phrases in ``_UNIT_PHRASES`` are read as units, so the other
parentheticals a description uses for something else — ``(du_type mf2to4)``,
``(APN)``, ``(0-1)``, ``(EPSG:4326)``, trip_generation's example rates — are
ignored instead of shown as a unit, and a column whose description states no
unit simply gets no suffix. A description stating its unit in prose rather
than in a parenthetical is a modelling gap, not a display one: it is fixed
where the unit is declared (``models/analysis/**``), not by a second table
here.

The map is keyed by *table* as well as column because one column name means
different units in different models: ``transport_ghg.co2e_total_kg`` is a
daily figure while ``building_water_ghg.co2e_total_kg`` is annual.

Model files are parsed once per process (~230 files, cached), the same way
``sqlmesh_tables`` reads a model's ``--`` description block: the metadata is
the model's own, and a Python copy of it would be a second source of truth
that silently drifts. `tests/workspace/test_analysis_column_units.py` pins the
derivation against the real project, including every unit-bearing phrase the
analysis models use.
"""

from __future__ import annotations

import re
from pathlib import Path

from brewgis.workspace.services.base_canvas_schema import BaseCanvasSchema

_MODELS_ROOT = Path(__file__).resolve().parents[2] / "sqlmesh" / "models"

# Parenthetical phrase used by a model's column_descriptions -> unit shown
# after the value. Kept to exact phrases: an unrecognized parenthetical is not
# a unit we know, so the value is shown bare rather than mislabelled.
_UNIT_PHRASES: dict[str, str] = {
    "acres": "acres",
    "sq ft": "sq ft",
    "acre-feet": "acre-ft",
    "acre-feet per year": "acre-ft/yr",
    "miles": "mi",
    "miles per day": "mi/day",
    "miles per year": "mi/yr",
    "miles per person per day": "mi/person/day",
    "miles per household per day": "mi/hh/day",
    "miles per person per year": "mi/person/yr",
    "miles per household per year": "mi/hh/yr",
    "km": "km",
    "people per acre": "people/acre",
    "intersections per square mile": "intersections/sq mi",
    "trips per day": "trips/day",
    "tons": "tons",
    "hours": "hr",
    "MET-hours": "MET-hr",
    "kg per year": "kg/yr",
    "kg per day": "kg/day",
    "kg per person per year": "kg/person/yr",
    "kg per person per day": "kg/person/day",
    "kWh per year": "kWh/yr",
    "kWh per sq ft per year": "kWh/sq ft/yr",
    "kWh per sq metre per year": "kWh/m²/yr",
    "MWh per year": "MWh/yr",
    "litres per year": "L/yr",
    "litres per person per day": "L/person/day",
    "litres per sq metre per year": "L/m²/yr",
    "mm per year, numerically litres per square metre per year": "mm/yr",
    "$": "$",
    "$ per year": "$/yr",
    "$ per unit": "$/unit",
    "$ per unit per year": "$/unit/yr",
    "$ per VMT": "$/mi",
    "% as 0-100": "%",
    "F": "°F",
    "DALYs per year": "DALYs/yr",
    "deaths per year": "deaths/yr",
}

# A description states exactly one unit in practice; matching the longest
# phrase first keeps "$ per year" from being shadowed by "$".
_PHRASES_BY_LENGTH = sorted(_UNIT_PHRASES, key=len, reverse=True)

_PAREN_RE = re.compile(r"\(([^()]*)\)")
# `column_descriptions (` ... `)` in a SQL MODEL block. The capture runs
# through the closing paren so the entry regex can see where the *last* entry
# ends — nothing else in the block ends with `)` on its own line.
_SQL_DESCRIPTIONS_RE = re.compile(
    r"column_descriptions\s*\((.*?\n\s*\))\s*,?", re.DOTALL
)
_SQL_ENTRY_RE = re.compile(r"(\w+)\s*=\s*'(.*?)'(?=\s*(?:,\s*\n|\n\s*\)))", re.DOTALL)
# `column_descriptions={` ... `}` in a Python model, whose values are plain or
# parenthesized (implicitly concatenated) string literals.
_PY_DESCRIPTIONS_RE = re.compile(
    r"column_descriptions\s*=\s*\{(.*?\n\s*\})\s*,?", re.DOTALL
)
_PY_ENTRY_RE = re.compile(r'"(\w+)":\s*(?:\(\s*)?(".*?"|\(.*?\))\s*\)?\s*,?', re.DOTALL)
_PY_STRING_RE = re.compile(r'"(.*?)"', re.DOTALL)

_cache: dict[str, dict[str, str]] | None = None
_descriptions_cache: dict[str, dict[str, str]] | None = None


def _unit_from_description(description: str) -> str:
    """Return the unit a column description declares, or ``""``.

    The unit is the first parenthetical that is a known unit phrase — a
    description names the metric's unit before any parenthetical about the
    inputs it was derived from (see ``energy_demand.energy_gas_res``, whose
    ``(kWh per year)`` precedes the ``(therms)`` it converts from).
    """
    for match in _PAREN_RE.finditer(description):
        for phrase in _PHRASES_BY_LENGTH:
            if match.group(1) == phrase:
                return _UNIT_PHRASES[phrase]
    return ""


def _normalized(text: str) -> str:
    """Collapse a description's whitespace, including implicit concatenation."""
    return " ".join(text.replace("''", "'").split())


def _sql_descriptions(text: str) -> dict[str, str]:
    """Column descriptions declared in a SQL ``MODEL`` DDL block."""
    block = _SQL_DESCRIPTIONS_RE.search(text)
    if not block:
        return {}
    return {
        match.group(1): _normalized(match.group(2))
        for match in _SQL_ENTRY_RE.finditer(block.group(1))
    }


def _python_descriptions(text: str) -> dict[str, str]:
    """Column descriptions declared in a Python model's ``model(...)`` call."""
    block = _PY_DESCRIPTIONS_RE.search(text)
    if not block:
        return {}
    descriptions: dict[str, str] = {}
    for match in _PY_ENTRY_RE.finditer(block.group(1)):
        parts = _PY_STRING_RE.findall(match.group(2))
        descriptions[match.group(1)] = _normalized(" ".join(parts))
    return descriptions


def model_column_descriptions() -> dict[str, dict[str, str]]:
    """Return ``{table: {column: description}}`` for every model that declares one.

    Parsed once per process. Exposed (alongside :func:`unit_phrases`) so the
    coverage test can check the derivation against the descriptions the
    lexicon does not recognize.
    """
    global _descriptions_cache  # noqa: PLW0603 — process-lifetime memo
    if _descriptions_cache is not None:
        return _descriptions_cache

    described: dict[str, dict[str, str]] = {}
    if _MODELS_ROOT.exists():
        paths = sorted(_MODELS_ROOT.rglob("*.sql")) + sorted(_MODELS_ROOT.rglob("*.py"))
        for path in paths:
            text = path.read_text()
            if "column_descriptions" not in text:
                continue
            descriptions = (
                _sql_descriptions(text)
                if path.suffix == ".sql"
                else _python_descriptions(text)
            )
            # Merged, not replaced: a region twin declares the same table name
            # with its own source's columns (``fresno`` and ``sacog`` each
            # publish ``assessor_parcels_raw``), and both sets describe the
            # table a layer registered under that name reads.
            table = described.setdefault(path.stem, {})
            for column, description in descriptions.items():
                table.setdefault(column, description)

    _descriptions_cache = described
    return described


def _load() -> dict[str, dict[str, str]]:
    """Return ``{table: {column: unit}}`` for every column declaring a unit.

    Only recognized units are kept, so a lookup miss is "no unit known"
    rather than an empty string to fall back from.
    """
    global _cache  # noqa: PLW0603 — process-lifetime memo, like the schema cache
    if _cache is not None:
        return _cache

    _cache = {
        table: {
            column: unit
            for column, description in descriptions.items()
            if (unit := _unit_from_description(description))
        }
        for table, descriptions in model_column_descriptions().items()
    }
    return _cache


def column_units(table: str) -> dict[str, str]:
    """Return ``{column: unit}`` for the model that publishes *table*."""
    return dict(_load().get(table, {}))


def unit_phrases() -> dict[str, str]:
    """Return the parenthetical phrases read as units, for tests."""
    return dict(_UNIT_PHRASES)


def resolve_column_unit(table: str, column: str) -> str:
    """Display unit suffix for *column* as it appears in *table*, or ``""``.

    The model that publishes *table* wins — it is the only thing that can
    tell ``co2e_total_kg`` per day from ``co2e_total_kg`` per year — then the
    base canvas schema, which covers the per-parcel columns every
    canvas-derived table carries. Pass ``table=""`` for a column whose table
    is not a model (the canvas view the parcel tab reads, an imported layer).
    """
    return column_units(table).get(column, "") or BaseCanvasSchema.unit(column)
