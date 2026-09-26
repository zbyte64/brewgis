# ruff: noqa: ANN201, ARG002
"""Tests for the built-form fill blueprint profiles.

Each profile is what SQLMesh instantiates one ``built_form_fill.fill_<pk>``
model from, so the source reference it bakes is what the model selects from.
Requires a PostgreSQL+PostGIS database.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from django.db import connection

from brewgis.sqlmesh.macros.built_form_fill_blueprints import built_form_fill_profiles
from tests.factories import WorkspaceFactory

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture
def imported_base_schema(base_canvas_table) -> Iterator[None]:
    """A base-canvas-shaped table in a schema no model publishes."""
    with connection.cursor() as cursor:
        cursor.execute("DROP SCHEMA IF EXISTS imported CASCADE")
        cursor.execute("CREATE SCHEMA imported")
        cursor.execute(
            "CREATE TABLE imported.base_canvas (LIKE public.base_canvas INCLUDING ALL)"
        )
    yield
    with connection.cursor() as cursor:
        cursor.execute("DROP SCHEMA IF EXISTS imported CASCADE")


@pytest.mark.integration
class TestSourceRef:
    """What the fill model reads its rows from."""

    def test_an_imported_base_is_referenced_as_a_table(self, imported_base_schema):
        """A base canvas need not be a SQLMesh model: the picker offers every
        loaded table with the base-canvas columns, and one no model publishes
        has no snapshot to depend on — it is selected from by name."""
        workspace = WorkspaceFactory(
            base_table="imported.base_canvas", fill_built_form=True
        )

        (profile,) = [
            profile
            for profile in built_form_fill_profiles()
            if profile["model_table"] == f"fill_{workspace.pk}"
        ]

        assert profile["source_ref"] == "imported.base_canvas"

    def test_a_model_base_is_referenced_as_a_model(self, base_canvas_table):
        """A model's FQN is what gives the fill model a real dependency on it,
        so a plan rebuilds the fill when the base model is rebuilt."""
        with connection.cursor() as cursor:
            cursor.execute("DROP SCHEMA IF EXISTS modeled CASCADE")
            cursor.execute("CREATE SCHEMA modeled")
            cursor.execute(
                "CREATE TABLE modeled.base_canvas_reconciled "
                "(LIKE public.base_canvas INCLUDING ALL)"
            )
        try:
            workspace = WorkspaceFactory(
                base_table="modeled.base_canvas_reconciled", fill_built_form=True
            )

            (profile,) = [
                profile
                for profile in built_form_fill_profiles()
                if profile["model_table"] == f"fill_{workspace.pk}"
            ]
        finally:
            with connection.cursor() as cursor:
                cursor.execute("DROP SCHEMA IF EXISTS modeled CASCADE")

        assert profile["source_ref"] == "brewgis.modeled.base_canvas_reconciled"
