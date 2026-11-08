"""Workspace input blueprint profiles — one set of analysis-input models per workspace.

Everything a scenario's analysis reads besides its parcels and Building Types —
environmental constraint layers, trip-length zones, food outlets, the road
network, and (for a workspace imported from a package) the base canvas itself —
is a model of the workspace's own ``wsp<workspace_pk>`` schema, resolved from the
``Workspace`` row:

=====================  ==========================================================
``Workspace`` field    what it selects
=====================  ==========================================================
``local_srid``         the CRS every one of these models measures and projects in
``extent``             the bounding box the public fetches cover
``constraint_source``  ``public``: FEMA flood zones + NWI wetlands fetched over
                       the extent; ``package``: the package's constraint layers
``trip_length_source`` ``gravity``: no zones (``trip_lengths`` rescales the gravity
                       model); ``package``: the package's trip-length zones
``public_data_source`` ``fetch``: OpenStreetMap food outlets and the Overture road
                       network fetched over the extent; ``package``: the
                       package's copies
``package_dir``        where those package parts (and the base canvas) are read from
=====================  ==========================================================

So the analysis of a workspace is a function of that workspace alone: no region,
no project-wide CRS, no other workspace's data. Each input has one model every
workspace gets — ``constraint_layers``, ``trip_length_zones``, ``food_pois``,
``road_subsegments`` (and what is built over them) — which the analysis reads as
``brewgis.<workspace_schema>.<name>`` whatever the source, and which reads its
source model by name (``_INPUT_MODELS``). Each source model is its own file and
covers only the workspaces that use it, selected by a subset name passed to the
macro (``@workspace_blueprints('public_constraints')``, see ``SUBSETS``).

Nothing here is built until an analysis asks for it: ``analysis.pipeline``
selects a workspace's inputs for exactly the modules a run requests, and a built
input is never restated by a run (its inputs are the extent and the package, not
the scenario).

Every workspace with an ``extent`` gets a profile; one without (its base table
has no geometry yet) gets none and its launches are refused as not configured
for analysis (``analysis.launch.scenario_analysis_errors``).

``workspace_profiles()`` reads the live database, so the model set always matches
the workspaces that exist. It is a function rather than a module-level constant
for the reason documented in ``region_blueprints``: SQLMesh serializes
module-level values into the macro's ``python_env`` with ``repr()`` and evaluates
them standalone, which cannot express the result of a live query.
"""

from __future__ import annotations

from typing import Any

import sqlglot
from sqlglot import exp
from sqlmesh import macro

#: Input variable -> (the ``Workspace`` source field, source value -> the model
#: the input reads). Each workspace input has one consumer model, declared in one
#: file, that reads its source model by name — ``FROM
#: brewgis.@{workspace_schema}.@{constraint_input}`` — rather than one file per
#: source declaring the same model: SQLMesh caches a file's blueprint expansion
#: by its mtime, not by the rows the expansion comes from, so two files
#: declaring one name would both claim it from a stale cache the moment a
#: workspace's source changes, and the project would stop loading.
_INPUT_MODELS: dict[str, tuple[str, dict[str, str]]] = {
    "constraint_input": (
        "constraint_source",
        {"public": "constraints_public", "package": "constraints_package_raw"},
    ),
    "trip_length_input": (
        "trip_length_source",
        {"gravity": "trip_zones_none", "package": "trip_zones_package_raw"},
    ),
    "food_pois_input": (
        "public_data_source",
        {"fetch": "food_pois_fetch_raw", "package": "food_pois_package_raw"},
    ),
    "road_subsegments_input": (
        "public_data_source",
        {
            "fetch": "road_subsegments_fetch_raw",
            "package": "road_subsegments_package_raw",
        },
    ),
}

# Profile keys spliced into object names (``brewgis.@{workspace_schema}.x``),
# rendered as bare identifiers rather than string literals.
_IDENTIFIER_VARS = {"workspace_schema", *_INPUT_MODELS}

# Package part file names inside an unpacked package directory (the archive
# layout ``services.workspace_package`` writes and validates).
PART_FILES = {
    "base_canvas": "base_canvas.parquet",
    "constraint_layers": "constraint_layers.parquet",
    "trip_length_zones": "trip_length_zones.parquet",
    "food_pois": "food_pois.parquet",
    "road_subsegments": "road_subsegments.parquet",
}

#: Subset name -> ``(profile key, value)``: the workspaces whose profile has that
#: value cover the model file; ``None`` is every workspace, and ``package_base``
#: keys on the base-canvas part being present. Plain data, not predicates:
#: SQLMesh serializes what the macro references with ``repr()``.
SUBSETS: dict[str, tuple[str, str] | None] = {
    "all": None,
    "package_base": ("base_canvas_parquet", ""),
    "public_constraints": ("constraint_source", "public"),
    "package_constraints": ("constraint_source", "package"),
    "gravity_trip_zones": ("trip_length_source", "gravity"),
    "package_trip_zones": ("trip_length_source", "package"),
    "fetched_public_data": ("public_data_source", "fetch"),
    "package_public_data": ("public_data_source", "package"),
}


def _in_subset(profile: dict[str, Any], subset: str) -> bool:
    rule = SUBSETS[subset]
    if rule is None:
        return True
    key, value = rule
    if subset == "package_base":
        return profile[key] != value
    return profile[key] == value


def workspace_profiles() -> list[dict[str, Any]]:
    """Per-workspace blueprint facts for every workspace with an extent.

    ``*_parquet`` is the absolute path of a package part the workspace reads,
    or an empty string when it reads none (the subsets key on that).
    """
    import django

    django.setup()

    from brewgis.sqlmesh.macros.analysis_blueprints import _drop_inherited_connection
    from brewgis.workspace.models import Workspace
    from brewgis.workspace.services.workspace_extent import extent_bounds

    _drop_inherited_connection()

    profiles: list[dict[str, Any]] = []
    for workspace in Workspace.objects.exclude(extent=None).order_by("pk"):
        min_x, min_y, max_x, max_y = extent_bounds(workspace.extent)
        root = workspace.package_root()
        parts = {
            f"{part}_parquet": str(root / filename) if root is not None else ""
            for part, filename in PART_FILES.items()
        }
        # A part is read only where the workspace's source selects it; the base
        # canvas is read whenever the workspace was imported.
        if workspace.constraint_source != "package":
            parts["constraint_layers_parquet"] = ""
        if workspace.trip_length_source != "package":
            parts["trip_length_zones_parquet"] = ""
        if workspace.public_data_source != "package":
            parts["food_pois_parquet"] = ""
            parts["road_subsegments_parquet"] = ""
        profiles.append(
            {
                "workspace_pk": int(workspace.pk),
                "workspace_schema": workspace.input_schema,
                "local_srid": int(workspace.local_srid),
                "extent_min_x": min_x,
                "extent_min_y": min_y,
                "extent_max_x": max_x,
                "extent_max_y": max_y,
                "constraint_source": workspace.constraint_source,
                "trip_length_source": workspace.trip_length_source,
                "public_data_source": workspace.public_data_source,
                # The source model each input reads, by name (see _INPUT_MODELS).
                **{
                    variable: models[getattr(workspace, source_field)]
                    for variable, (source_field, models) in _INPUT_MODELS.items()
                },
                **parts,
            }
        )
    return profiles


def workspace_subset_profiles(subset: str) -> list[dict[str, Any]]:
    """The profiles of *subset* (a ``SUBSETS`` key)."""
    if subset not in SUBSETS:
        msg = (
            f"workspace_blueprints: unknown subset {subset!r}; known: {sorted(SUBSETS)}"
        )
        raise ValueError(msg)
    return [profile for profile in workspace_profiles() if _in_subset(profile, subset)]


def _variable_sql(name: str, value: object) -> str:
    """Render one blueprint variable as SQL literal text (identifiers bare)."""
    if name in _IDENTIFIER_VARS:
        return str(value)
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    return repr(value)  # int / float -> exact numeric literal text


@macro()
def workspace_blueprints(evaluator, subset: exp.Expr | None = None) -> list[exp.Expr]:  # noqa: ANN001, ARG001
    """One blueprint entry per workspace in *subset* (default: every workspace).

    Returned inside one enclosing tuple, like ``analysis_blueprints``: SQLMesh
    only wraps a multi-element rendered list itself, so a single workspace's
    profile would otherwise be read as its individual variables.
    """
    name = "all" if subset is None else subset.name
    entries = [
        sqlglot.parse_one(
            "("
            + ", ".join(
                f"{key} := {_variable_sql(key, value)}"
                for key, value in profile.items()
            )
            + ")",
            into=exp.Tuple,
        )
        for profile in workspace_subset_profiles(name)
    ]
    return [exp.Tuple(expressions=entries)]
