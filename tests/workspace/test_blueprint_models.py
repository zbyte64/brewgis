"""Tests for the registration gate around blueprinted Python models.

``@model(blueprints=[...])`` cannot express "zero instances": SQLMesh reads a
declared but empty list as one *unblueprinted* instance, which for a model whose
query is assembled from its blueprint renders a SELECT with no projections — and
project load then dies with "Query missing select statements", taking the whole
project (and the SQLMesh UI that loads it) down for a feature nobody opted into.

These pin the helper the blueprinted Python models register through, which
applies the declaration only when there is at least one instance (see
``brewgis/sqlmesh/blueprint_models.py``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from brewgis.sqlmesh.blueprint_models import register_blueprint_model

if TYPE_CHECKING:
    from collections.abc import Callable


class _Declaration:
    """Stand-in for the ``model(...)`` object a module would decorate with."""

    def __init__(self) -> None:
        self.applied: list[Callable[[], None]] = []

    def __call__(self, func: Callable[[], None]) -> Callable[[], None]:
        self.applied.append(func)
        return func


def _execute() -> None: ...


class TestRegisterBlueprintModel:
    """What the helper hands back, and to what it hands it."""

    def test_registers_nothing_without_profiles(self) -> None:
        declaration = _Declaration()

        assert register_blueprint_model(declaration, _execute, []) is _execute
        assert declaration.applied == []

    def test_applies_the_declaration_once_per_instance(self) -> None:
        declaration = _Declaration()
        profiles: list[dict[str, Any]] = [{"model_table": "fill_1"}]

        assert register_blueprint_model(declaration, _execute, profiles) is _execute
        assert declaration.applied == [_execute]
