"""Auto-registration of analysis result views as Layer objects.

After a successful SQLMesh plan, materialized views are created in PostGIS.
This module creates or updates corresponding Layer objects in the workspace
so the results are discoverable by the tile server and map component.
"""

from __future__ import annotations

import logging
from typing import Any

from django.db import connection
from django.db.models import Q
from django.db.models import QuerySet

from brewgis.workspace.analysis.module_registry import get_primary_column
from brewgis.workspace.models import Layer
from brewgis.workspace.models import LayerGroup
from brewgis.workspace.models import Scenario
from brewgis.workspace.models import ScenarioType
from brewgis.workspace.models import StyleClass
from brewgis.workspace.models import SymbologyConfig
from brewgis.workspace.models import Workspace

logger = logging.getLogger(__name__)

BASE_CANVAS_LAYER_KEY = "base_canvas"
"""Stable Layer.key for a workspace's base canvas layer.

Fixed (not derived from the table name) so that switching
``Workspace.base_table`` to a different table updates this same Layer in
place instead of leaving the old one orphaned in the Layers panel.
"""

PAINTED_FEATURES_LAYER_KEY = "painted_features"
"""Stable Layer.key for a workspace's painted-features overlay.

One Layer per workspace, shared across all of its scenarios (mirroring
``BASE_CANVAS_LAYER_KEY``) — only its map source is swapped to the active
scenario's canvas view at render time; the Layer row itself (and its
SymbologyConfig) persists independent of any single scenario.
"""

_PAINTED_FEATURES_GROUP_NAME = "Scenario Layers"

_PAINTED_TRUE_COLOR = "#ffeb3b"
_PAINTED_FALSE_COLOR = "#e0e0e0"

BASE_CANVAS_SYMBOLOGY_COLUMN = "built_form_key"
"""Column the base canvas layer's symbology defaults to.

The base canvas is the workspace's parcel fabric, and the built form key is
what a planner reads off it — a numeric column (the generic default for a
result table) says nothing about what is drawn there.
"""

BASE_CANVAS_SYMBOLOGY_PALETTE = "glasbey"
"""Palette the base canvas layer's symbology defaults to.

A geography holds 40+ built form keys — the default workspace library alone
is 96 types — which is well past every other categorical palette's 8-12
stops. Glasbey carries ~200 distinct colors, so each key still reads as its
own color instead of repeating one of ten.
"""


def ensure_painted_features_layer(
    workspace: Workspace, *, schema: str = "", table: str = ""
) -> Layer:
    """Get or create the workspace's painted-features overlay Layer.

    Creates a ``categorical`` SymbologyConfig keyed on the ``uf_is_painted``
    boolean column (present on every scenario's canvas view — see
    ``canvas_view_manager.py``) with the historical yellow/gray colors as
    defaults, editable afterwards via the normal Symbology editor like any
    other layer. Idempotent: a workspace that already has this Layer (and
    classes) is returned unchanged.

    ``schema``/``table`` — the currently-active scenario's canvas view, if
    known — are (re)stamped on every call so the Symbology editor's "color
    by" column dropdown has something real to introspect (``uf_is_painted``
    among others). Map rendering itself never reads these back: map.py
    always swaps this layer's actual source to whichever scenario is active
    at request time.
    """
    layer, created = Layer.objects.get_or_create(
        workspace=workspace,
        key=PAINTED_FEATURES_LAYER_KEY,
        defaults={
            "name": "Painted Features",
            "description": "Highlights parcels painted in the active scenario.",
            "layer_source": "postgis",
            "db_table": table,
            "db_schema": schema,
            "geometry_type": "fill",
        },
    )
    if not created and table and (layer.db_table != table or layer.db_schema != schema):
        layer.db_table = table
        layer.db_schema = schema
        layer.save(update_fields=["db_table", "db_schema"])

    if created:
        group, _ = LayerGroup.objects.get_or_create(
            workspace=workspace,
            name=_PAINTED_FEATURES_GROUP_NAME,
            # High display_order so this group sorts after other named
            # groups (e.g. "Analysis Results") by default, approximating the
            # old hardcoded behavior of always drawing the paint highlight on
            # top — still just a default; fully draggable afterwards.
            defaults={"display_order": 9000},
        )
        layer.group = group
        layer.save(update_fields=["group"])

    config, config_created = SymbologyConfig.objects.get_or_create(
        layer=layer,
        defaults={
            "symbology_type": "categorical",
            "attribute_column": "uf_is_painted",
            "default_color": _PAINTED_FALSE_COLOR,
            "default_opacity": 0.3,
            "null_handling": "custom_color",
            "null_color": _PAINTED_FALSE_COLOR,
            "auto_generated": True,
        },
    )
    if config_created:
        StyleClass.objects.create(
            symbology=config,
            label="true",
            color=_PAINTED_TRUE_COLOR,
            sort_order=0,
        )
        StyleClass.objects.create(
            symbology=config,
            label="false",
            color=_PAINTED_FALSE_COLOR,
            sort_order=1,
        )

    return layer


def visible_layers_for_panel(
    workspace: Workspace, scenario: Scenario | None = None
) -> QuerySet[Layer]:
    """Layers the map shell renders for *scenario*.

    The workspace's own layers — base canvas, the painted-features overlay
    and imported data, none of which belong to a scenario — plus the active
    scenario's own layers. Each scenario owns an instance of every analysis
    model (see ``sqlmesh/macros/analysis_blueprints.py``), so without the
    scenario filter a workspace shows the same analysis once per scenario it
    has been run in, and the map draws all of those instances on top of each
    other.

    The painted-features overlay only has a source while a scenario is
    active (see ``view_workspace_map``), so it's excluded here otherwise —
    keeping it out of the queryset (rather than skipping it in the template)
    means its "Scenario Layers" group header doesn't show up empty either.
    """
    if scenario is None:
        layers = workspace.layers.filter(scenario__isnull=True)
    else:
        layers = workspace.layers.filter(
            Q(scenario__isnull=True) | Q(scenario=scenario)
        )
    if scenario is None or scenario.scenario_type != ScenarioType.ALTERNATIVE:
        layers = layers.exclude(key=PAINTED_FEATURES_LAYER_KEY)
    return layers


def _get_table_columns(schema: str, table: str) -> list[dict[str, Any]]:
    """Introspect column metadata from PostGIS for a given table/view.

    Returns a list of dicts with keys: column_name, data_type, numeric.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                c.column_name,
                c.data_type,
                CASE WHEN c.data_type IN ('integer', 'bigint', 'numeric', 'real', 'double precision')
                     THEN true ELSE false END AS is_numeric
            FROM information_schema.columns c
            WHERE c.table_schema = %s
              AND c.table_name = %s
            ORDER BY c.ordinal_position
            """,
            [schema, table],
        )
        return [
            {
                "column_name": row[0],
                "data_type": row[1],
                "numeric": row[2],
            }
            for row in cursor.fetchall()
        ]


def _classify_geometry_type_name(geom_type: str) -> str | None:
    """Map a PostGIS geometry type name to a Layer geometry_type.

    Accepts names in either ``geometry_columns.type`` form ("POLYGON",
    "MULTILINESTRING") or ``ST_GeometryType()`` form ("ST_Polygon",
    "ST_MultiPoint"). Returns None for generic/unrecognized names (e.g. the
    bare "geometry" type PostGIS reports for many computed view columns), so
    callers can fall back to inspecting actual row data instead of guessing.
    """
    lowered = geom_type.lower()
    if "polygon" in lowered:
        return "fill"
    if "line" in lowered:
        return "line"
    if "point" in lowered:
        return "circle"
    return None


def _get_geometry_type(schema: str, table: str) -> str:
    """Determine the geometry type of a PostGIS table/view.

    Returns: "fill", "line", or "circle".

    ``geometry_columns.type`` is frequently just "GEOMETRY" for computed or
    view-based geometry columns (PostGIS can't statically infer a specific
    subtype), which would otherwise fall through to a wrong guess. When that
    happens, this samples one row's actual geometry via ``ST_GeometryType``
    instead of assuming.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT f_geometry_column, type
            FROM geometry_columns
            WHERE f_table_schema = %s AND f_table_name = %s
            """,
            [schema, table],
        )
        row = cursor.fetchone()
        if not row:
            return "fill"

        geom_column, catalog_type = row
        classified = _classify_geometry_type_name(catalog_type)
        if classified is not None:
            return classified

        cursor.execute(
            f"""
            SELECT ST_GeometryType({connection.ops.quote_name(geom_column)})
            FROM {connection.ops.quote_name(schema)}.{connection.ops.quote_name(table)}
            WHERE {connection.ops.quote_name(geom_column)} IS NOT NULL
            LIMIT 1
            """  # noqa: S608 -- schema/table/column are catalog-sourced, not user input
        )
        sample = cursor.fetchone()
        if sample:
            classified = _classify_geometry_type_name(sample[0])
            if classified is not None:
                return classified
        return "fill"


def _find_numeric_column(columns: list[dict[str, Any]], table: str) -> str | None:
    """Find the numeric column that best represents this result table.

    Prefers the analysis module's known headline output column (see
    ``module_registry.TABLE_PRIMARY_COLUMN``), then falls back to a handful
    of common cross-module names like 'population'/'households', and only
    then to the first numeric column that isn't an id or geometry column.
    """
    numeric_columns = {col["column_name"] for col in columns if col["numeric"]}
    primary_column = get_primary_column(table)
    if primary_column and primary_column in numeric_columns:
        return primary_column

    preferred = {
        "acres_developable",
        "developable_proportion",
        "population",
        "households",
        "dwelling_units_total",
        "employment_total",
        "employment",
        "total_population",
        "total_households",
    }
    for col in columns:
        if col["numeric"] and col["column_name"] in preferred:
            return col["column_name"]  # type: ignore[no-any-return]

    # Fallback: first numeric column that looks like a data column
    skip_patterns = {"id", "pk", "parcel_id", "geom"}
    for col in columns:
        if col["numeric"] and col["column_name"] not in skip_patterns:
            return col["column_name"]  # type: ignore[no-any-return]

    return None


def _auto_configure_symbology(
    layer: Layer,
    column: str,
    *,
    palette_name: str | None = None,
) -> None:
    """Generate *layer*'s symbology for *column* from the table's data.

    Delegates to the auto-generation pipeline (statistics → classification →
    palette) rather than writing a bare ``graduated`` config: a config with no
    ``StyleClass`` rows and no palette renders as one flat color and shows up
    in the Symbology editor as "Manual", which is not what "auto-generated"
    should mean. The palette comes from *palette_name* when the caller has one
    (the base canvas draws built forms in glasbey), else from the table's
    registered default when it has one (``module_registry.TABLE_PALETTE``).

    This runs on every registration of an auto-managed layer, so re-running an
    analysis recomputes the breaks against the values the new run published
    instead of leaving the previous run's breaks in place.

    Best-effort by design: registration's job is the Layer, which is already
    saved by the time this runs, and a result view that is empty, unreadable,
    or whose table has since been dropped must not fail the plan's aftermath —
    the layer stays registered and its symbology is editable by hand. The
    failure is logged with its stack trace rather than swallowed silently.
    """
    # Imported here: ``symbology.auto`` imports this module (BASE_CANVAS_LAYER_KEY).
    from brewgis.workspace.symbology.auto import auto_generate_symbology

    try:
        auto_generate_symbology(layer, column, palette_name=palette_name, num_classes=5)
    except Exception:
        logger.exception(
            "Symbology auto-generation failed for layer %s (column %s)",
            layer.key,
            column,
        )
        return

    logger.info(
        "Auto-generated symbology for %s on column %s",
        layer.key,
        column,
    )


def register_result_layer(
    workspace_id: int,
    schema: str,
    table: str,
    *,
    name: str | None = None,
    description: str | None = None,
    key: str | None = None,
    group_name: str | None = None,
    scenario_id: int | None = None,
) -> Layer | None:
    """Register a PostGIS view/table as a Layer in the workspace.

    Creates a new Layer or updates an existing one. Keeps the layer's
    symbology in step with the registered table: an auto-generated config (a
    new layer's, or one no user has saved by hand) is (re)built from the
    table's current values — class breaks, palette and all — every time this
    runs, so re-registering after a rerun refreshes the breaks instead of
    leaving stale ones. A config the user has saved is left untouched.

    What the config is built *on* depends on the layer: the base canvas
    (``key=BASE_CANVAS_LAYER_KEY``) draws ``built_form_key`` in the glasbey
    palette, every other layer its headline numeric column in the palette
    registered for its result table.

    Args:
        workspace_id: Workspace primary key.
        schema: PostGIS schema containing the table.
        table: PostGIS table/view name.
        name: Human-readable layer name (auto-generated if None).
        description: Layer description.
        key: Explicit Layer key. Defaults to the table name. Pass a stable
            key (e.g. ``"base_canvas"``) when the underlying table can change
            over time and re-registration should update the same Layer
            rather than create a new one per table name.
        group_name: LayerGroup to place this layer under (created if it
            doesn't exist yet). Only applied while the layer has no group of
            its own, so a group the user picked by hand (e.g. via drag/drop
            in the Layer Groups panel) is never overwritten on a later rerun.
        scenario_id: Scenario this result belongs to — the map and the Layers
            panel only show it while that scenario is active (see
            ``visible_layers_for_panel``). None for workspace-level layers.

    Returns:
        The Layer instance, or None if registration fails.
    """
    try:
        workspace = Workspace.objects.get(pk=workspace_id)
    except Workspace.DoesNotExist:
        logger.error("Workspace %s not found, cannot register layer", workspace_id)
        return None

    # Determine geometry type
    geometry_type = _get_geometry_type(schema, table)

    # Generate human-readable name
    layer_name = name or table.replace("_", " ").title()

    # Look up columns for auto-configuration
    columns = _get_table_columns(schema, table)

    layer_key = key or table

    # What the layer's symbology is built on: the base canvas draws its built
    # form key (categorical, glasbey), everything else its headline numeric
    # column in the registry's palette for that result table.
    if layer_key == BASE_CANVAS_LAYER_KEY and any(
        column["column_name"] == BASE_CANVAS_SYMBOLOGY_COLUMN for column in columns
    ):
        symbology_column: str | None = BASE_CANVAS_SYMBOLOGY_COLUMN
        symbology_palette: str | None = BASE_CANVAS_SYMBOLOGY_PALETTE
    else:
        symbology_column = _find_numeric_column(columns, table)
        symbology_palette = None

    layer, created = Layer.objects.update_or_create(
        workspace=workspace,
        key=layer_key,
        defaults={
            "name": layer_name,
            "description": description or f"Analysis result: {table}",
            "layer_source": "postgis",
            "db_table": table,
            "db_schema": schema,
            "geometry_type": geometry_type,
            "scenario_id": scenario_id,
        },
    )

    logger.info(
        "%s Layer '%s' (key=%s) in workspace %s",
        "Created" if created else "Updated",
        layer_name,
        layer_key,
        workspace_id,
    )

    if group_name and layer.group_id is None:
        group, _ = LayerGroup.objects.get_or_create(
            workspace=workspace, name=group_name
        )
        layer.group = group
        layer.save(update_fields=["group"])

    # Auto-generate symbology for a layer whose config is still auto-managed:
    # a brand-new layer, or an existing one being re-registered by a rerun
    # whose config nobody has saved by hand. Recomputing on re-registration is
    # the point — a rerun publishes a result view whose values (and so whose
    # class breaks, and whose headline column) may differ from the run that
    # produced the breaks the layer is currently rendering. A config the user
    # has saved (``auto_generated=False``, set by views/symbology.py) is never
    # touched. A layer whose table offers no column to classify (no
    # ``built_form_key`` for the base canvas, no numeric column otherwise)
    # keeps whatever it has, or gets none when it is new.
    existing_config = SymbologyConfig.objects.filter(layer=layer).first()
    if symbology_column and (existing_config is None or existing_config.auto_generated):
        _auto_configure_symbology(
            layer, symbology_column, palette_name=symbology_palette
        )

    return layer
