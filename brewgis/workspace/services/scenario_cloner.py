"""Scenario creation service — creates ALTERNATIVE scenarios under a parent.

Every ALTERNATIVE scenario has a *parent* (a workspace's BASE scenario, or
another ALTERNATIVE it was cloned from). No
:class:`~brewgis.workspace.models.PaintedCanvas` rows are ever copied from
the parent — a fresh scenario shares the same base data (copy-on-write). A
SQL view is created so tile servers see the (initially transparent) canvas.
"""

from __future__ import annotations

import contextlib
import logging

from brewgis.workspace.models import Layer
from brewgis.workspace.models import Scenario
from brewgis.workspace.models import ScenarioType
from brewgis.workspace.services.scenario_canvas import materialize_scenario_canvas

logger = logging.getLogger(__name__)


def create_scenario(
    *,
    parent: Scenario,
    name: str,
    description: str = "",
    base_year: int | None = None,
    horizon_year: int | None = None,
) -> Scenario:
    """Create a new ALTERNATIVE scenario under *parent*.

    Parameters
    ----------
    parent : Scenario
        The scenario this new one is based on (typically the workspace's
        BASE scenario). Determines ``workspace`` and, unless overridden,
        ``base_year``/``horizon_year``.
    name : str
        Display name for the new scenario.
    description : str
        Optional description.
    base_year : int | None
        Override base year. Inherits from *parent* when ``None``.
    horizon_year : int | None
        Override horizon year. Inherits from *parent* when ``None``.

    Returns
    -------
    Scenario
        The newly created ALTERNATIVE scenario, with its canvas view and
        Layer already registered.

    Raises
    ------
    django.db.IntegrityError
        If a scenario with the same slug already exists in the workspace.
    """
    new_scenario = Scenario.objects.create(
        name=name,
        description=description or parent.description,
        workspace=parent.workspace,
        scenario_type=ScenarioType.ALTERNATIVE,
        parent=parent,
        base_year=base_year if base_year is not None else parent.base_year,
        horizon_year=horizon_year if horizon_year is not None else parent.horizon_year,
    )

    # Materialize the canvas view (SQLMesh owns it) so tile servers can query it.
    # No PaintedCanvas rows are copied — canvas starts blank (pass-through to base).
    materialize_scenario_canvas(new_scenario)
    logger.info(
        "Created canvas view for scenario %s (%s)", new_scenario.pk, new_scenario.slug
    )

    _register_canvas_layer(new_scenario, source_name=parent.name)
    return new_scenario


def clone_scenario(
    *,
    source: Scenario,
    name: str,
    description: str = "",
    horizon_year: int | None = None,
) -> Scenario:
    """Clone *source* into a new ALTERNATIVE scenario.

    Thin wrapper around :func:`create_scenario` — *source* becomes the new
    scenario's ``parent``. No paint data is copied (copy-on-write).
    """
    return create_scenario(
        parent=source,
        name=name,
        description=description,
        horizon_year=horizon_year,
    )


def _register_canvas_layer(scenario: Scenario, *, source_name: str) -> None:
    """Get-or-create the Layer that exposes *scenario*'s canvas view.

    Auto-generates symbology the first time the Layer is created.
    """
    view_qualifier = f"{scenario.target_schema}.scenario_{scenario.slug}_canvas"
    layer, created = Layer.objects.get_or_create(
        workspace=scenario.workspace,
        key=f"scenario_{scenario.slug}_canvas",
        defaults={
            "name": f"{scenario.name} — Canvas",
            "description": (
                f"Canvas view for scenario '{scenario.name}' (based on {source_name})"
            ),
            "workspace": scenario.workspace,
            "geometry_type": "fill",
            "display_order": 0,
            "layer_source": "canvas_view",
            "db_table": view_qualifier,
        },
    )
    if created:
        from brewgis.workspace.symbology.auto import auto_generate_symbology

        with contextlib.suppress(Exception):
            auto_generate_symbology(layer)


def _get_layer_model() -> type[Layer]:
    """Lazy import to avoid circular dependency at module level."""
    from brewgis.workspace.models import Layer

    return Layer
