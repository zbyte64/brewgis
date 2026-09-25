"""Discovery of sqlmesh-managed tables/views available for import.

SQLMesh's gateway-managed virtual layer exposes each model as a queryable
view named ``<schema>.<table>`` where *schema* is the model's schema segment
(e.g. ``analysis.core_end_state``). Physical, fingerprinted tables live in
``sqlmesh__<schema>`` and are never meant to be queried directly, so this
module only enumerates the virtual-layer schemas.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from pathlib import Path
from typing import Any

from django.db import connection

from brewgis.sqlmesh.model_names import MODEL_SCHEMA_PREFIX
from brewgis.sqlmesh.model_names import RESULT_SCHEMA_PREFIX
from brewgis.workspace.models import Workspace
from brewgis.workspace.services.base_canvas_schema import BaseCanvasSchema

# ``scenario_canvas`` holds the per-scenario canvas models (one model per
# ALTERNATIVE scenario, ``canvas_<scenario_id>`` — see
# ``sqlmesh/macros/scenario_canvas_blueprints.py`` for why they can't be named
# after the views they create). Those models are implementation detail backing
# the scenario-named canvas views; listing them as importable tables would put
# them in the data catalog and the base-canvas picker.
#
# ``ascn<scenario_pk>`` holds each analyzed scenario's analysis models
# (``sqlmesh/macros/analysis_blueprints.py``) for the same reason: the result
# views those models publish are the scenario-facing objects.
#
# ``built_form_fill`` holds the per-workspace built-form fill models
# (``sqlmesh/macros/built_form_fill_blueprints.py``), which a workspace reads as
# its base canvas when ``Workspace.fill_built_form`` is on. A workspace's own
# fill output is derived from the base table it is already configured with, so
# offering it back as an importable source would let a workspace base itself on
# its own derivative.
_EXCLUDED_SCHEMAS = {
    "public",
    "information_schema",
    "sqlmesh_state",
    "scenario_canvas",
    "built_form_fill",
}

_POLYGON_TYPES = {"polygon", "multipolygon"}
_LINE_TYPES = {"linestring", "multilinestring"}

_MODELS_ROOT = Path(__file__).resolve().parents[2] / "sqlmesh" / "models"

# Must match the `project=` value in brewgis/sqlmesh/config.py — sqlmesh
# qualifies every model's UI/FQN path as "<project>.<schema>.<table>".
SQLMESH_PROJECT_NAME = "brewgis"


def sqlmesh_model_ui_url(schema: str, table: str) -> str:
    """Deep link to a model's page in the ``sqlmesh ui`` data catalog.

    *schema* is the schema the *table* is read from, which is not always the
    schema of the model behind it: a scenario's analysis result views are
    published in ``analysis__scenario_<pk>`` while their models live in the
    internal ``ascn<pk>`` schema (see ``_model_schema``). Resolving it here
    keeps every caller — the layer panel, the symbology editor and the import
    picker alike — pointing at a model the UI actually has.
    """
    from django.conf import settings

    return (
        f"{settings.SQLMESH_UI_URL}/data-catalog/models/"
        f"{SQLMESH_PROJECT_NAME}.{_model_schema(schema)}.{table}"
    )


def _model_schema(schema: str) -> str:
    """Return the schema of the SQLMesh model a table in *schema* belongs to.

    A scenario's analysis result views are published by that scenario's models
    into ``analysis__scenario_<pk>``, while the models themselves live in the
    internal ``ascn<pk>`` schema (see
    ``sqlmesh/macros/analysis_blueprints.py``). A UI link to a result view has
    to name the model that owns it — there is no model at the result schema.
    Any other schema is a model's own schema and is returned unchanged.
    """
    if not schema.startswith(RESULT_SCHEMA_PREFIX):
        return schema
    return MODEL_SCHEMA_PREFIX + schema[len(RESULT_SCHEMA_PREFIX) :]


def _known_model_table_stems() -> frozenset[str]:
    """Bare table names of every real SQLMesh model in the model tree.

    A model's table name is the stem of the file that declares it —
    ``models/<category>/<table>.sql`` or ``.py``, so a model written in Python
    counts the same as one written in SQL (``models/python/trip_distribution.py``
    publishes ``<schema>.trip_distribution``) — and only the schema is
    templated: it can be blueprinted per region, e.g. ``@{region}``, but the
    table name never is (see ``_model_descriptions_by_table_name``). Checking
    a table name against actual model filenames is therefore the reliable
    signal for "is this really a SQLMesh model" that ``sqlmesh_link_for_table``
    gates on before trusting a live-table match. Files whose name starts with
    ``_`` are helper modules a model imports (``models/python/_predict.py``),
    not models.

    ``list_sqlmesh_tables()`` enumerates *any* view/table living in a
    non-excluded Postgres schema — including views this codebase creates
    itself outside SQLMesh, like a scenario's painted-features canvas view
    (``scenario_<slug>_canvas``, see ``Scenario.base_layer_source``), which
    lives in its own non-excluded ``scenario_<slug>`` schema. That schema
    check alone isn't enough to tell a real model apart from one of those.
    """
    if not _MODELS_ROOT.exists():
        return frozenset()
    return frozenset(
        path.stem
        for path in _MODELS_ROOT.rglob("*")
        if path.suffix in {".sql", ".py"} and not path.stem.startswith("_")
    )


def _blueprinted_model_tables() -> frozenset[tuple[str, str]]:
    """``(schema, table)`` of the models the project generates from the database.

    Every other model is named after its file — ``models/<category>/<table>``
    (see ``_known_model_table_stems``) — so its table name can be verified
    against the model tree. A blueprinted model is named after a *row*, and
    its name therefore exists nowhere but the database: a workspace with the
    built-form fill on has one ``built_form_fill.fill_<workspace pk>`` (see
    ``sqlmesh/macros/built_form_fill_blueprints.py``). Reading the same rows
    the blueprint macro filters on (``Workspace.fill_built_form``) is what
    makes this authoritative: the model is in the project exactly while its
    workspace has the feature enabled.

    The name comes from ``Workspace.effective_base_table`` — the one place
    that resolves which layer the workspace reads — so a link built from this
    can never disagree with the table the base canvas layer is registered
    under.
    """
    tables: set[tuple[str, str]] = set()
    for workspace in Workspace.objects.filter(fill_built_form=True).only(
        "pk", "fill_built_form"
    ):
        schema, _, table = workspace.effective_base_table().rpartition(".")
        tables.add((schema or "public", table))
    return frozenset(tables)


def _model_backed_tables() -> frozenset[tuple[str, str]]:
    """``(schema, table)`` pairs a live SQLMesh model can be read through.

    The tables the catalog discovers in model schemas whose name is a real
    model file's, plus the blueprint-generated models
    (``_blueprinted_model_tables``) the catalog deliberately omits.

    The two differ because the catalog answers "what may a workspace import as
    a source" — it excludes ``built_form_fill`` so a workspace cannot base
    itself on its own fill output (``_EXCLUDED_SCHEMAS``) — while this answers
    "what is a model-backed table a layer may be drawing". The workspace's
    base canvas layer reads exactly that excluded fill model, so it is in this
    pool and not in that catalog.
    """
    stems = _known_model_table_stems()
    discovered = {
        (info.schema, info.table)
        for info in list_sqlmesh_tables()
        if info.table in stems
    }
    return frozenset(discovered | _blueprinted_model_tables())


def sqlmesh_link_for_table(
    schema: str,
    table: str,
    known: frozenset[tuple[str, str]] | None = None,
) -> str | None:
    """Return a SQLMesh UI link for ``schema.table``, or ``None``.

    The link names the model *behind* the table, not the table itself: a
    scenario's analysis result views live in ``analysis__scenario_<pk>`` while
    their models live in the internal ``ascn<pk>`` schema (see
    ``_model_schema``).

    Returns ``None`` unless ``(schema, table)`` is a table a live SQLMesh
    model is read through (see ``_model_backed_tables``) — which rules out
    both the non-model views that live in the same kind of schema
    (painted-features canvas views, imported shapefiles, Census/OSM tables)
    and a model that has never actually been built for this
    workspace/scenario.

    Pass ``known`` (a set of ``(schema, table)`` pairs, as built in
    ``sqlmesh_links_for_tables``) to avoid re-querying the catalog when
    checking several tables at once.
    """
    known_set = _model_backed_tables() if known is None else known
    if (schema, table) not in known_set:
        return None
    return sqlmesh_model_ui_url(schema, table)


def sqlmesh_links_for_tables(
    table_refs: dict[Any, tuple[str, str]],
) -> dict[Any, str]:
    """Map arbitrary keys -> SQLMesh UI links, for SQLMesh-backed tables.

    ``table_refs`` maps a caller-chosen key (e.g. ``Layer.pk``) to that
    record's raw ``(schema, table)``. Keys whose pair isn't a real SQLMesh
    model (per ``sqlmesh_link_for_table``) are simply omitted — callers
    look up ``links.get(key)`` and render nothing when absent.

    Resolves the model-backed table set once regardless of how many refs are
    passed, so this is the preferred entry point when linking a whole layer
    list (as opposed to ``sqlmesh_link_for_table`` for a single layer).
    """
    known = _model_backed_tables()
    links: dict[Any, str] = {}
    for key, (schema, table) in table_refs.items():
        link = sqlmesh_link_for_table(schema, table, known=known)
        if link is not None:
            links[key] = link
    return links


@dataclass(frozen=True)
class SqlmeshTableInfo:
    """One importable sqlmesh-managed table or view."""

    schema: str
    table: str
    has_geometry: bool
    geometry_type: str | None

    @property
    def qualified(self) -> str:
        return f"{self.schema}.{self.table}"


def _is_excluded_schema(schema: str) -> bool:
    """Whether *schema* holds objects that must not appear in the table catalog.

    ``scenario_canvas`` and ``ascn<scenario_pk>`` are internal model schemas:
    the scenario-facing objects are the views those models publish
    (``scenario_<slug>.scenario_<slug>_canvas`` / ``analysis__scenario_<pk>``).
    """
    return schema in _EXCLUDED_SCHEMAS or schema.startswith(
        ("pg_", "sqlmesh__", "ascn")
    )


def list_sqlmesh_tables() -> list[SqlmeshTableInfo]:
    """Return all tables/views in sqlmesh-managed (virtual-layer) schemas.

    Ordered by schema, then table name, with geometry-bearing tables first
    within each schema so they surface at the top of import pickers.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT t.table_schema, t.table_name
            FROM information_schema.tables t
            WHERE t.table_type IN ('BASE TABLE', 'VIEW')
            ORDER BY t.table_schema, t.table_name
            """
        )
        rows = cursor.fetchall()

        cursor.execute(
            "SELECT f_table_schema, f_table_name, type FROM geometry_columns"
        )
        geometry_rows = cursor.fetchall()

    geometry_by_table = {
        (schema, table): geom_type for schema, table, geom_type in geometry_rows
    }

    results = []
    for schema, table in rows:
        if _is_excluded_schema(schema):
            continue
        raw_geom_type = geometry_by_table.get((schema, table))
        has_geometry = raw_geom_type is not None
        geometry_type = None
        if raw_geom_type:
            lowered = raw_geom_type.lower()
            if lowered in _POLYGON_TYPES:
                geometry_type = "fill"
            elif lowered in _LINE_TYPES:
                geometry_type = "line"
            else:
                geometry_type = "circle"
        results.append(
            SqlmeshTableInfo(
                schema=schema,
                table=table,
                has_geometry=has_geometry,
                geometry_type=geometry_type,
            )
        )

    results.sort(key=lambda info: (info.schema, not info.has_geometry, info.table))
    return results


@dataclass(frozen=True)
class SqlmeshLayerCandidate:
    """A geometry-bearing sqlmesh table, enriched for the import picker."""

    schema: str
    table: str
    geometry_type: str
    columns: tuple[str, ...]
    created_at: datetime | None
    description: str

    @property
    def qualified(self) -> str:
        return f"{self.schema}.{self.table}"


def _strip_line_comments(text: str) -> str:
    """Blank out everything from ``--`` to end-of-line, character for character.

    Preserves the original length/offsets (blanks with spaces rather than
    truncating) so the result stays index-compatible with *text* — needed
    since callers use offsets found here to slice the original string.
    Otherwise a stray ``(``/``)`` mentioned inside a comment could also
    throw off paren-depth counting.
    """

    def _blank(line: str) -> str:
        idx = line.find("--")
        return line if idx == -1 else line[:idx] + " " * (len(line) - idx)

    return "\n".join(_blank(line) for line in text.splitlines())


def _model_block_end(text: str) -> int | None:
    """Return the index just past the closing paren of ``MODEL ( ... )``."""
    match = re.search(r"\bMODEL\s*\(", text)
    if not match:
        return None
    stripped = _strip_line_comments(text)
    depth = 1
    i = match.end()
    while i < len(stripped) and depth > 0:
        if stripped[i] == "(":
            depth += 1
        elif stripped[i] == ")":
            depth -= 1
        i += 1
    return i if depth == 0 else None


def _extract_model_description(text: str) -> str:
    """Return the ``--`` comment block immediately following ``MODEL (...)``.

    This is the codebase's convention for documenting a model in prose —
    see e.g. ``models/base_canvas/base_canvas_geometry.sql``. Returns ""
    when a model has no such trailing comment block.
    """
    end = _model_block_end(text)
    if end is None:
        return ""

    # `end` lands right after the closing `)` — still mid-line (the model's
    # trailing `;` usually follows immediately). Skip to the next line
    # before scanning for the blank line + comment block.
    next_newline = text.find("\n", end)
    rest = text[next_newline + 1 :] if next_newline != -1 else ""
    lines = rest.splitlines()
    idx = 0
    while idx < len(lines) and not lines[idx].strip():
        idx += 1

    desc_lines: list[str] = []
    while idx < len(lines) and lines[idx].strip().startswith("--"):
        desc_lines.append(lines[idx].strip()[2:].strip())
        idx += 1

    while desc_lines and not desc_lines[-1]:
        desc_lines.pop()
    return "\n".join(desc_lines).strip()


def _model_descriptions_by_table_name() -> dict[str, str]:
    """Map bare table name (sql filename stem) -> model description.

    SQLMesh models live at ``models/<category>/<table_name>.sql`` where
    ``<table_name>`` matches the trailing segment of the model's ``name``
    (blueprints only template the schema/region, never the table name), so
    the filename stem reliably identifies which model produced a given
    discovered table.
    """
    descriptions: dict[str, str] = {}
    if not _MODELS_ROOT.exists():
        return descriptions
    for path in _MODELS_ROOT.rglob("*.sql"):
        desc = _extract_model_description(path.read_text())
        if desc:
            descriptions[path.stem] = desc
    return descriptions


def _model_created_at() -> dict[tuple[str, str], datetime]:
    """Map (schema, table) -> earliest known SQLMesh snapshot timestamp.

    Approximates "created" as the first time this model name appeared in
    SQLMesh's own snapshot history (``sqlmesh_state._snapshots``) — not
    perfect (old snapshots can be purged), but the best signal available
    without parsing plan/apply logs.
    """
    _name_parts = 3  # "project"."schema"."table"
    created: dict[tuple[str, str], datetime] = {}
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT name, MIN(updated_ts) FROM sqlmesh_state._snapshots "
                "GROUP BY name"
            )
            rows = cursor.fetchall()
    except Exception:  # noqa: BLE001 — state schema may not exist in dev
        return created

    for name, min_ts in rows:
        parts = [p.strip('"') for p in name.split(".")]
        if len(parts) != _name_parts or min_ts is None:
            continue
        _project, schema, table = parts
        created[(schema, table)] = datetime.fromtimestamp(min_ts / 1000, tz=UTC)
    return created


def _all_columns_by_table() -> dict[tuple[str, str], list[str]]:
    """Map (schema, table) -> ordered column names, in one bulk query."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT table_schema, table_name, column_name FROM information_schema.columns "
            "WHERE column_name != 'geometry' "
            "ORDER BY table_schema, table_name, ordinal_position"
        )
        rows = cursor.fetchall()

    columns_by_table: dict[tuple[str, str], list[str]] = {}
    for schema, table, column in rows:
        columns_by_table.setdefault((schema, table), []).append(column)
    return columns_by_table


def list_sqlmesh_layer_candidates() -> list[SqlmeshLayerCandidate]:
    """Return geometry-bearing sqlmesh tables enriched for the import picker.

    Adds each table's columns, earliest known creation timestamp (from
    SQLMesh's own snapshot history), and a human-written description
    (parsed from the model's .sql file).
    """
    columns_by_table = _all_columns_by_table()
    created_by_table = _model_created_at()
    descriptions = _model_descriptions_by_table_name()

    return [
        SqlmeshLayerCandidate(
            schema=info.schema,
            table=info.table,
            geometry_type=info.geometry_type or "circle",
            columns=tuple(columns_by_table.get((info.schema, info.table), ())),
            created_at=created_by_table.get((info.schema, info.table)),
            description=descriptions.get(info.table, ""),
        )
        for info in list_sqlmesh_tables()
        if info.has_geometry
    ]


def get_table_preview(
    schema: str, table: str, limit: int = 8
) -> dict[str, object] | None:
    """Return column metadata and a small row sample for a sqlmesh table.

    Returns ``None`` when ``(schema, table)`` isn't a currently discovered
    sqlmesh table — callers MUST check this before trusting the input,
    since *schema*/*table* are interpolated directly into SQL below (they
    can't be bind parameters as identifiers) and this function is the only
    thing standing between a request and arbitrary-table access.
    """
    known = {(info.schema, info.table) for info in list_sqlmesh_tables()}
    if (schema, table) not in known:
        return None

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = %s "
            "ORDER BY ordinal_position",
            [schema, table],
        )
        columns = [{"name": name, "type": dtype} for name, dtype in cursor.fetchall()]

        # A table can have more than one geometry column (e.g. a raw
        # `geometry` plus a reprojected `local_geometry`) — the catalog is
        # the authoritative way to find all of them, a name check isn't
        # enough. Raw WKB isn't useful in a text preview, so all are
        # excluded from the sample-row query.
        cursor.execute(
            "SELECT f_geometry_column FROM geometry_columns "
            "WHERE f_table_schema = %s AND f_table_name = %s",
            [schema, table],
        )
        geometry_columns = {row[0] for row in cursor.fetchall()}

        display_columns = [
            c["name"] for c in columns if c["name"] not in geometry_columns
        ]
        select_list = ", ".join(f'"{name}"' for name in display_columns) or "1"
        q_schema = f'"{schema}"'
        q_table = f'"{table}"'
        cursor.execute(
            # schema/table validated against the known-tables set above
            f"SELECT {select_list} FROM {q_schema}.{q_table} LIMIT %s",  # noqa: S608
            [limit],
        )
        # Plain row tuples (not dicts) — Django templates can't do a dynamic
        # dict lookup by loop variable, so rows are zipped against
        # display_columns positionally in the template instead.
        rows = cursor.fetchall()

    return {
        "columns": columns,
        "display_columns": display_columns,
        "has_geometry": len(display_columns) != len(columns),
        "rows": rows,
    }


def _required_base_canvas_columns() -> frozenset[str]:
    """Columns a table must have to stand in as a workspace's base canvas.

    Requires every column in ``BaseCanvasSchema.COLUMN_NAMES`` (not just the
    non-nullable subset) — downstream consumers (painting, canvas views,
    symbology) read a fixed set of column names, so a table with a varied
    subset would break them at query time rather than at import time.
    """
    return frozenset(BaseCanvasSchema.COLUMN_NAMES)


def list_base_canvas_candidates() -> list[SqlmeshTableInfo]:
    """Return sqlmesh tables/views that contain every required base-canvas column.

    A table qualifies as a base canvas candidate when it already has all of
    ``BaseCanvasSchema.COLUMN_NAMES`` (e.g. sqlmesh's own
    ``base_canvas_reconciled`` models) — no further ETL/allocation is needed,
    the table can be adopted as-is.
    """
    required = _required_base_canvas_columns()
    if not required:
        return []

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT table_schema, table_name, column_name "
            "FROM information_schema.columns"
        )
        rows = cursor.fetchall()

    columns_by_table: dict[tuple[str, str], set[str]] = {}
    for schema, table, column in rows:
        columns_by_table.setdefault((schema, table), set()).add(column)

    return [
        info
        for info in list_sqlmesh_tables()
        if required.issubset(columns_by_table.get((info.schema, info.table), set()))
    ]
