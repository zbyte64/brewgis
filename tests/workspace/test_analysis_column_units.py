# ruff: noqa: ANN201
"""Tests for the units the UI suffixes onto model-published columns.

``services.analysis_column_units`` derives each unit from the model's own
``column_descriptions`` (the repository's declaration of what an output column
holds), so these tests run against the real SQLMesh project rather than a
fixture: they pin the derivation for the columns the map and the
feature-inspect panel show, and they fail loudly when a new model column
states a unit the lexicon does not read.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from brewgis.workspace.services.analysis_column_units import column_units
from brewgis.workspace.services.analysis_column_units import model_column_descriptions
from brewgis.workspace.services.analysis_column_units import resolve_column_unit
from brewgis.workspace.services.analysis_column_units import unit_phrases

_MODELS_ROOT = Path(__file__).resolve().parents[2] / "brewgis" / "sqlmesh" / "models"
_ANALYSIS_ROOT = _MODELS_ROOT / "analysis"
# The analysis Python models — their column_descriptions are dicts, not SQL,
# and they publish layers of their own (trip_distribution, trip_lengths).
_ANALYSIS_PYTHON_MODELS = (
    _MODELS_ROOT / "python" / "trip_distribution.py",
    _MODELS_ROOT / "python" / "trip_lengths.py",
)

# A parenthetical holding one of these words is stating a unit. Counts
# (people, jobs, households, units, trips, outlets) are deliberately absent:
# a row's label already names those, so they are rendered bare.
_UNIT_WORDS = (
    "acres",
    "sq ft",
    "sq metre",
    "acre-feet",
    "miles",
    "km",
    "tons",
    "hours",
    "kg",
    "kWh",
    "MWh",
    "litres",
    "per year",
    "per day",
    "$",
    "%",
    "DALY",
    "deaths",
    "F",
)

_PAREN_RE = re.compile(r"\(([^()]*)\)")


def _declared_columns(text: str) -> list[str]:
    """Return the column names a model declares, read off the raw lines.

    Entries sit on the declaration's own indentation level — a description
    continued across lines closes at a deeper indentation, so only the
    ``)``/``}`` at the declaration's level ends the block. This is an
    independent read of the same file, so the parser cannot agree with itself
    by construction; it caught the parser dropping each model's *last* entry.
    """
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if "column_descriptions" in line)
    indent = len(lines[start]) - len(lines[start].lstrip())
    entry = re.compile(
        r"\s*(\w+)\s*=" if "column_descriptions (" in lines[start] else r'\s*"(\w+)":'
    )

    names: list[str] = []
    for line in lines[start + 1 :]:
        stripped = line.strip()
        if (
            stripped.startswith((")", "}"))
            and (len(line) - len(line.lstrip())) <= indent
        ):
            break
        match = entry.match(line)
        if match:
            names.append(match.group(1))
    return names


def _described_columns() -> dict[str, dict[str, str]]:
    """Return ``{table: {column: description}}`` for every analysis model."""
    described = model_column_descriptions()
    tables = {path.stem for path in _ANALYSIS_ROOT.rglob("*.sql")} | {
        path.stem for path in _ANALYSIS_PYTHON_MODELS
    }
    return {table: described[table] for table in tables if table in described}


@pytest.mark.models
class TestColumnUnits:
    """Units derived from the SQLMesh models' own column descriptions."""

    def test_analysis_metric_units(self):
        """Each analysis headline metric carries the unit its model states."""
        expected = {
            ("total_ghg", "co2e_total"): "kg/yr",
            ("transport_ghg", "co2e_total_kg"): "kg/day",
            ("building_water_ghg", "co2e_total_kg"): "kg/yr",
            ("transport_ghg", "co2e_per_capita_kg"): "kg/person/day",
            ("building_water_ghg", "co2e_per_capita_kg"): "kg/person/yr",
            ("vmt", "vmt_total"): "mi/day",
            ("vmt", "vmt_per_hh"): "mi/hh/day",
            ("vmt", "vmt_annual"): "mi/yr",
            ("trip_generation", "trips_total"): "trips/day",
            ("trip_distribution", "trips_outbound"): "trips/day",
            ("internal_capture", "trips_external"): "trips/day",
            ("mode_choice", "mode_share_auto"): "",
            ("health_impacts", "net_dalys"): "DALYs/yr",
            ("health_impacts", "deaths_averted_pa"): "deaths/yr",
            ("physical_activity", "total_met_hours"): "MET-hr",
            ("water_demand", "water_demand_total"): "L/yr",
            ("energy_demand", "energy_total"): "kWh/yr",
            ("energy_demand", "energy_intensity_kwh_per_sqft"): "kWh/sq ft/yr",
            ("agriculture", "net_return"): "$",
            ("agriculture", "water_consumption_af"): "acre-ft",
            ("scenario_summary", "water_demand_total_af"): "acre-ft/yr",
            ("scenario_summary", "energy_demand_total_mwh"): "MWh/yr",
            ("stormwater_runoff", "runoff_volume_acre_ft"): "acre-ft",
            ("core_end_state", "annual_eto_mm"): "mm/yr",
            ("core_end_state", "outdoor_water_rate"): "L/m²/yr",
            ("sprawl_index", "population_density"): "people/acre",
            ("sprawl_cost", "infrastructure_cost_per_hh_annual"): "$/yr",
            ("tree_canopy", "surface_temp_f"): "°F",
            ("trip_lengths", "avg_trip_length_km"): "km",
        }

        wrong = {
            (table, column): (column_units(table).get(column, ""), want)
            for (table, column), want in expected.items()
            if column_units(table).get(column, "") != want
        }
        assert not wrong, f"model-derived units changed: {wrong}"

    def test_same_column_name_keeps_its_per_model_unit(self):
        """The unit is keyed by table: ``co2e_total_kg`` is daily in one model
        and annual in another, and a name-only lookup would mislabel one."""
        assert resolve_column_unit("transport_ghg", "co2e_total_kg") == "kg/day"
        assert resolve_column_unit("building_water_ghg", "co2e_total_kg") == "kg/yr"

    def test_counts_and_unknown_tables_carry_no_unit(self):
        """Counts stay bare, and a table no model publishes is never guessed."""
        assert resolve_column_unit("core_end_state", "pop") == ""
        assert resolve_column_unit("core_increment", "du") == ""
        assert resolve_column_unit("scenario_summary", "total_population") == ""
        assert resolve_column_unit("food_access", "healthy_count") == ""
        assert resolve_column_unit("some_imported_layer", "co2e_total") == ""
        assert resolve_column_unit("some_imported_layer", "pop") == ""

    def test_base_canvas_columns_fall_back_to_the_schema(self):
        """A canvas column keeps its unit whatever table it is read from."""
        assert resolve_column_unit("", "area_parcel") == "acres"
        assert resolve_column_unit("", "area_gross_acres") == "acres"
        assert resolve_column_unit("", "rent_burden_pct") == "%"
        assert resolve_column_unit("", "median_income") == "$/yr"


@pytest.mark.models
class TestColumnUnitsCoverage:
    """The derivation against every analysis model, so a new one cannot slip
    past with a unit the UI silently drops."""

    def test_every_analysis_model_is_parsed(self):
        """Each analysis model declaring column descriptions was read."""
        described = _described_columns()
        expected = {path.stem for path in _ANALYSIS_ROOT.rglob("*.sql")} | {
            path.stem for path in _ANALYSIS_PYTHON_MODELS
        }
        assert expected <= set(described)

    def test_every_declared_column_is_parsed(self):
        """No column is dropped — including the one that closes the block.

        Regression: the entry pattern used to require a trailing comma, so the
        last column of every model's ``column_descriptions`` was invisible and
        its unit never reached the UI.
        """
        described = model_column_descriptions()

        missing: dict[str, list[str]] = {}
        for path in sorted(_MODELS_ROOT.rglob("*.sql")) + sorted(
            _MODELS_ROOT.rglob("*.py")
        ):
            text = path.read_text()
            if "column_descriptions" not in text:
                continue
            declared = _declared_columns(text)
            parsed = set(described.get(path.stem, {}))
            if dropped := [column for column in declared if column not in parsed]:
                missing[f"{path.relative_to(_MODELS_ROOT)}"] = dropped

        assert not missing, f"declared columns the parser dropped: {missing}"

    def test_unit_bearing_descriptions_are_all_recognized(self):
        """A description stating a unit is either read or fails this test.

        The pre-condition is the column resolving to no unit at all: a column
        that already has one (``trips_school``, whose description mentions the
        9.7% school-trip share) has nothing to recover, while a parenthetical
        holding a unit word under a unit-less column means the UI shows that
        value bare.
        """
        unrecognized: list[str] = []
        for table, columns in _described_columns().items():
            units = column_units(table)
            for column, description in columns.items():
                if units.get(column):
                    continue
                for text in _PAREN_RE.findall(description):
                    recognized = any(text == phrase for phrase in unit_phrases())
                    if not recognized and any(w in text for w in _UNIT_WORDS):
                        unrecognized.append(f"{table}.{column}: ({text})")

        assert not unrecognized, (
            "unit-bearing descriptions the lexicon does not read: "
            + "; ".join(unrecognized)
        )

    def test_every_lexicon_phrase_is_used(self):
        """No stale phrase: each one is still what a model description says."""
        descriptions = [
            description
            for columns in model_column_descriptions().values()
            for description in columns.values()
        ]
        unused = [
            phrase
            for phrase in unit_phrases()
            if not any(f"({phrase})" in text for text in descriptions)
        ]
        assert not unused, f"lexicon phrases no model states any more: {unused}"
