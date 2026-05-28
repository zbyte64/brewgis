"""Scenario cloning service — creates alternative scenarios from a base.

Cloning creates a fresh :class:`~brewgis.workspace.models.Scenario` of type
``ALTERNATIVE`` with *parent* pointing to the source scenario.  No
:class:`~brewgis.workspace.models.PaintedCanvas` rows are copied — a fresh
alternative shares the same base data (copy-on-write).  A SQL view is created
so tile servers see the (initially transparent) canvas.
"""

from __future__ import annotations

import contextlib
import logging

from brewgis.workspace.models import Layer
from brewgis.workspace.models import Scenario
from brewgis.workspace.models import ScenarioType
from brewgis.workspace.services.base_canvas_manager import DEFAULT_BASE_CANVAS_TABLE
from brewgis.workspace.services.canvas_view_manager import create_canvas_view

logger = logging.getLogger(__name__)


def clone_scenario(
    *,
    source: Scenario,
    name: str,
    description: str = "",
    horizon_year: int | None = None,
    base_canvas_table: str = DEFAULT_BASE_CANVAS_TABLE,
) -> Scenario:
    """Clone *source* into a new ALTERNATIVE scenario.

    Parameters
    ----------
    source : Scenario
        The base scenario to clone from.
    name : str
        Display name for the new scenario.
    description : str
        Optional description.
    horizon_year : int | None
        Override horizon year.  Inherits from *source* when ``None``.
    base_canvas_table : str
        Fully-qualified base canvas table name (``schema.table``).
        Used to create the SQL view for tile server compatibility.

    Returns
    -------
    Scenario
        The newly created ALTERNATIVE scenario.

    Raises
    ------
    django.db.IntegrityError
        If a scenario with the same slug already exists in the workspace.
    """
    new_scenario = Scenario.objects.create(
        name=name,
        description=description or source.description,
        workspace=source.workspace,
        scenario_type=ScenarioType.ALTERNATIVE,
        parent=source,
        base_year=source.base_year,
        horizon_year=horizon_year if horizon_year is not None else source.horizon_year,
    )

    # Create the canvas SQL view so tile servers can query it.
    # No PaintedCanvas rows are copied — canvas starts blank (pass-through to base).
    create_canvas_view(new_scenario, base_canvas_table)
    logger.info(
        "Created canvas view for scenario %s (%s)", new_scenario.pk, new_scenario.slug
    )

    # Register a Layer so the tile server picks up the view.
    view_qualifier = f"{new_scenario.target_schema}.scenario_{new_scenario.slug}_canvas"
    layer, created = Layer.objects.get_or_create(
        workspace=source.workspace,
        key=f"scenario_{new_scenario.slug}_canvas",
        defaults={
            "name": f"{new_scenario.name} — Canvas",
            "description": (
                f"Canvas view for scenario '{new_scenario.name}' "
                f"(cloned from {source.name})"
            ),
            "workspace": source.workspace,
            "geometry_type": "fill",
            "display_order": 0,
            "layer_source": "canvas_view",
            "db_table": view_qualifier,
        },
    )
    # Auto-generate symbology for newly created canvas layers.
    if created:
        from brewgis.workspace.symbology.auto import auto_generate_symbology

        with contextlib.suppress(Exception):
            auto_generate_symbology(layer)

    return new_scenario


def _get_layer_model() -> type[Layer]:
    """Lazy import to avoid circular dependency at module level."""
    from brewgis.workspace.models import Layer

    return Layer
