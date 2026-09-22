# ruff: noqa: ARG002
"""Tests for the built-form key matching rule.

The rule exists twice — once in Python (the paint UI's lookup) and once in SQL
(the analysis models' join) — and the two must agree: a key that resolves to a
Building Type in one and not the other is a parcel that paints fine and then
analyzes to zero.
"""

from __future__ import annotations

import pytest
from django.db import connection

from brewgis.sqlmesh.macros.built_form_keys import (
    normalize_built_form_key as sql_normalize,
)
from brewgis.workspace.services.built_form_keys import normalize_built_form_key

# One entry per key shape either runtime sees: display names (what the paint
# surfaces write), ETL slugs (what the base canvas carries), and the edges.
NORMALIZATIONS: list[tuple[str, str]] = [
    ("Courtyard Apartment", "courtyard apartment"),
    ("courtyard apartment", "courtyard apartment"),
    ("Single-Family Detached - Standard", "single family detached   standard"),
    ("  Courtyard Apartment  ", "courtyard apartment"),
    ("bt__medium_density_detached_residential", "medium density detached residential"),
    ("bt__Courtyard_Apartment", "courtyard apartment"),
    ("bf__stacked-flats", "stacked flats"),
    ("pt__Office - Low Rise", "office   low rise"),
    ("mixed_use", "mixed use"),
    ("mixed use", "mixed use"),
    ("bt__", ""),
    ("", ""),
]


class TestNormalizeBuiltFormKey:
    """The Python rule, on its own."""

    @pytest.mark.parametrize(("key", "expected"), NORMALIZATIONS)
    def test_matches_a_display_name_to_its_etl_slug(
        self, key: str, expected: str
    ) -> None:
        assert normalize_built_form_key(key) == expected

    def test_drops_only_one_prefix(self) -> None:
        """A second prefix is content, not decoration."""
        assert normalize_built_form_key("bt__bt__x") == "bt  x"


@pytest.mark.models
class TestSqlRuleMatchesPythonRule:
    """The macro the analysis models join on applies the same normalization."""

    def test_agrees_on_every_key_shape(self, db) -> None:
        keys = [key for key, _expected in NORMALIZATIONS]
        # Render the macro itself (a bare `%s` placeholder as its argument), so
        # this pins the SQL the models actually run, not a copy of it.
        expression = sql_normalize(None, "%s")

        with connection.cursor() as cursor:
            cursor.execute("SELECT " + ", ".join([expression] * len(keys)), keys)
            from_sql = cursor.fetchone()

        assert from_sql == tuple(normalize_built_form_key(key) for key in keys)
