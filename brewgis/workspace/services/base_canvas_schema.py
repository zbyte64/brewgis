"""Base Canvas Schema — single source of truth for all ~82 base canvas columns.

Provides column metadata, category groupings, and classification sets used by
the canvas view manager, ETL pipeline, dbt models, and symbology system.

The canonical source is the ``BaseCanvasColumn`` Django model.  At first access
the class reads from the database; if the model table does not exist yet (e.g.
during initial migration), it falls back to the hardcoded ``ColumnDef``
definitions compiled below.

Column categories (per ``planning/v2/09-base-canvas.md``):

    1. Identification & Geometry
    2. Land Use & Built Form
    3. Area & Parcel Geometry
    4. Demographics
    5. Housing by Type
    6. Employment
    7. Building Area
    8. Irrigation
    9. Equity & Environmental Quality

**Static columns** (passed through verbatim by the painting system):
    id, id_source, geometry_key, geometry, land_development_category,
    built_form_key, intersection_density, area_gross

All other columns are **paintable/summable**.
"""
# ruff: noqa: E501  # long lines in docstring & DDL

from __future__ import annotations

from dataclasses import dataclass

from django.db.models import Field


@dataclass(frozen=True, slots=True)
class ColumnDef:
    """Definition of a single base canvas column."""

    name: str
    label: str
    pg_type: str
    unit: str
    metatype: str
    aggregation_hint: str
    behavior_category: str
    nullable: bool = False
    default_value: float | str | None = 0.0


# ── Static columns — passed through verbatim, never painted ───────────
_STATIC_COLUMN_NAMES: frozenset[str] = frozenset(
    {
        "id",
        "id_source",
        "geography_id",
        "geometry_key",
        "geometry",
        "land_development_category",
        "built_form_key",
        "intersection_density",
        "area_gross",
    }
)

# ── Nullable columns ──────────────────────────────────────────────────
_NULLABLE_NAMES: frozenset[str] = frozenset(
    {"id_source", "geography_id", "geometry_key", "built_form_key"}
)


def _build_hardcoded_state() -> dict:
    """Build fallback schema state by introspecting the ``BaseCanvas`` model.

    Derives ``ColumnDef`` objects from ``BaseCanvas._meta.fields`` when
    Django is ready.  If the model is not available (Django not yet
    initialized), returns a minimal state from the static column sets.
    """
    try:
        from brewgis.workspace.models import BaseCanvas
    except (ImportError, RuntimeError):
        return _build_minimal_state()

    names: list[str] = []
    col_map: dict[str, ColumnDef] = {}
    from django.db.models import Field

    for field in BaseCanvas._meta.get_fields():
        if not isinstance(field, Field):
            continue
        if (
            (field.auto_created and not field.primary_key)
            or field.is_relation
            or field.column is None
        ):  # type: ignore[union-attr]
            continue

        name: str = field.column  # type: ignore[assignment]
        internal_type: str = field.get_internal_type()
        name_lower: str = name.lower()
        names.append(name)

        pg_type = _derive_pg_type(field, internal_type)
        nullable = _derive_nullable(field, internal_type, name_lower)
        default = _derive_default(field, internal_type, name_lower)
        metatype = _derive_metatype(internal_type, name_lower)
        agg_hint = _derive_agg_hint(metatype)
        behavior = "static" if name in _STATIC_COLUMN_NAMES else "paintable"

        col_map[name] = ColumnDef(
            name=name,
            label=name,
            pg_type=pg_type,
            unit="",
            metatype=metatype,
            aggregation_hint=agg_hint,
            behavior_category=behavior,
            nullable=nullable,
            default_value=default,
        )

    col_names = tuple(names)
    return {
        "column_names": col_names,
        "column_map": col_map,
        "static_columns": _STATIC_COLUMN_NAMES,
        "paintable_columns": frozenset(
            name for name in col_names if name not in _STATIC_COLUMN_NAMES
        ),
        "summable_columns": frozenset(
            name for name in col_names if name not in _STATIC_COLUMN_NAMES
        ),
        "non_null_columns": frozenset(
            name for name in col_names if name not in _NULLABLE_NAMES
        ),
    }


def _build_minimal_state() -> dict:
    """Return a minimal schema state when Django is not yet initialized.

    Only the static column names are known — enough for basic lookups.
    """
    col_names = tuple(_STATIC_COLUMN_NAMES)
    return {
        "column_names": col_names,
        "column_map": {},
        "static_columns": _STATIC_COLUMN_NAMES,
        "paintable_columns": frozenset(),
        "summable_columns": frozenset(),
        "non_null_columns": frozenset(),
    }


def _derive_pg_type(field: Field, internal_type: str) -> str:
    """Map a Django field type to its PostgreSQL type name."""
    pg_map = {
        "BigAutoField": "BIGSERIAL",
        "AutoField": "SERIAL",
        "FloatField": "DOUBLE PRECISION",
        "IntegerField": "INTEGER",
        "BigIntegerField": "BIGINT",
    }
    if internal_type in pg_map:
        return pg_map[internal_type]
    if internal_type == "CharField":
        return f"VARCHAR({field.max_length})"
    if internal_type == "GeometryField":
        return "GEOMETRY(GEOMETRY, 4326)"
    if internal_type == "BooleanField":
        return "BOOLEAN"
    return "DOUBLE PRECISION"


def _derive_nullable(field: Field, internal_type: str, name_lower: str) -> bool:
    """Determine if a column is nullable."""
    if name_lower in _NULLABLE_NAMES:
        return True
    if internal_type in ("BigAutoField", "AutoField"):
        return False
    return field.null


def _derive_default(
    field: Field, internal_type: str, name_lower: str
) -> float | str | None:
    """Derive a sensible default value for a column."""
    if name_lower in ("id_source", "built_form_key", "geography_id", "geometry_key"):
        return None
    if name_lower == "land_development_category":
        return ""
    if internal_type in ("FloatField",):
        return 0.0
    if hasattr(field, "default") and field.default is not None:
        return field.default
    return 0.0


def _derive_metatype(internal_type: str, name_lower: str) -> str:
    """Derive the metatype from the field type and name."""
    if internal_type in ("GeometryField",):
        return "geometry"
    if name_lower in ("id", "id_source", "geography_id", "geometry_key"):
        return "identity"
    if name_lower in ("land_development_category", "built_form_key"):
        return "classification"
    return "count"


def _derive_agg_hint(metatype: str) -> str:
    """Derive the aggregation hint from the metatype."""
    if metatype in ("identity", "geometry", "classification"):
        return "first"
    if metatype == "density":
        return "avg"
    return "sum"


def _load_from_db() -> dict | None:
    """Attempt to load schema from the ``BaseCanvasColumn`` model.

    Returns ``None`` if the model table does not exist yet (migration in progress).
    """
    try:
        from brewgis.workspace.models import BaseCanvasColumn as CanvasColumn

        qs = CanvasColumn.objects.all().order_by("display_order")
        if not qs.exists():
            return None

        names: list[str] = []
        col_map: dict[str, ColumnDef] = {}
        for row in qs:
            names.append(row.name)
            col_map[row.name] = ColumnDef(
                name=row.name,
                label=row.label or "",
                pg_type=row.pg_type or "DOUBLE PRECISION",
                unit=row.unit or "",
                metatype=row.metatype or "count",
                aggregation_hint=row.aggregation_hint or "sum",
                behavior_category=row.behavior_category or "paintable",
                nullable=row.nullable,
                default_value=row.default_value
                if row.default_value is not None
                else 0.0,
            )
        col_names = tuple(names)

        static_cols = _load_static_column_names(col_map)
        return {
            "column_names": col_names,
            "column_map": col_map,
            "static_columns": static_cols,
            "paintable_columns": frozenset(
                name for name in col_names if name not in static_cols
            ),
            "summable_columns": frozenset(
                name for name in col_names if name not in static_cols
            ),
            "non_null_columns": _load_non_null_column_names(col_map),
        }
    except Exception:  # noqa: BLE001
        # Table doesn't exist yet — caller falls back to hardcoded
        return None


def _load_static_column_names(
    col_map: dict[str, ColumnDef],
) -> frozenset[str]:
    """Derive static column set from the live column map."""
    return frozenset(
        name for name, col in col_map.items() if col.behavior_category == "static"
    )


def _load_non_null_column_names(
    col_map: dict[str, ColumnDef],
) -> frozenset[str]:
    """Derive NOT NULL column set from the live column map."""
    return frozenset(name for name, col in col_map.items() if not col.nullable)


# Module-level cache populated once at first access.
_cache: dict | None = None


def _get_cache() -> dict:
    """Return the schema cache, loading from DB or falling back to hardcoded."""
    global _cache
    if _cache is not None:
        return _cache

    # Try the DB first
    db_state = _load_from_db()
    if db_state is not None:
        _cache = db_state
        return _cache

    # Fall back to hardcoded
    _cache = _build_hardcoded_state()
    return _cache


def invalidate_cache() -> None:
    """Force a reload of the schema cache on next access.

    Call this after migrations or data changes to ``BaseCanvasColumn``.
    """
    global _cache
    _cache = None


# ── Re-export: BaseCanvasSchema class with same API ───────────────────


class BaseCanvasSchema:
    """Single source of truth for base canvas table structure.

    Reads from the ``BaseCanvasColumn`` Django model at first access,
    falling back to hardcoded column definitions when the DB table is
    not yet available (during initial migration).
    """

    COLUMN_NAMES: tuple[str, ...] = _get_cache()["column_names"]
    STATIC_COLUMNS: frozenset[str] = _get_cache()["static_columns"]
    PAINTABLE_COLUMNS: frozenset[str] = _get_cache()["paintable_columns"]
    SUMMABLE_COLUMNS: frozenset[str] = _get_cache()["summable_columns"]
    NON_NULL_COLUMNS: frozenset[str] = _get_cache()["non_null_columns"]

    _COLUMNS: dict[str, ColumnDef] = _get_cache()["column_map"]

    # Static columns for backward compatibility
    STATIC_COLUMN_NAMES: frozenset[str] = _get_cache()["static_columns"]

    @classmethod
    def columns(cls) -> dict[str, ColumnDef]:
        """Return ``{column_name: ColumnDef}`` for all base canvas columns."""
        return dict(cls._COLUMNS)

    @classmethod
    def get(cls, name: str) -> ColumnDef | None:
        """Get ``ColumnDef`` for *name*, or ``None`` if not found."""
        return cls._COLUMNS.get(name)

    @classmethod
    def default_value(cls, name: str) -> float | str | None:
        """Return the default value for *name*, or 0.0 if unknown."""
        col = cls.get(name)
        return col.default_value if col is not None else 0.0

    @classmethod
    def create_table_sql(cls, table_name: str = "public.base_canvas") -> str:
        """Generate the ``CREATE TABLE`` DDL for the base canvas table.

        Args:
            table_name: Fully qualified target table name (default ``public.base_canvas``).
        """
        col_defs: list[str] = []
        for name in cls.COLUMN_NAMES:
            col = cls.get(name)
            if col is None:
                continue
            if name == "id":
                col_defs.append("    id SERIAL PRIMARY KEY")
                continue
            if name == "geometry":
                col_defs.append("    geometry GEOMETRY(MultiPolygon, 4326) NOT NULL")
                continue
            nullable = " NOT NULL" if name in cls.NON_NULL_COLUMNS else ""
            col_defs.append(f"    {name} {col.pg_type}{nullable}")

        joined = ",\n".join(col_defs)
        return f"""CREATE TABLE IF NOT EXISTS {table_name} (
{joined}
);
"""

    @classmethod
    def create_indexes_sql(cls, table_name: str = "public.base_canvas") -> list[str]:
        """Return SQL statements for recommended indexes on the base canvas table.

        Args:
            table_name: Fully qualified target table name (default ``public.base_canvas``).
        """
        gist_idx = (
            "CREATE INDEX IF NOT EXISTS idx_base_canvas_geometry "
            f"ON {table_name} USING GIST (geometry)"
        )
        btree_idx = (
            "CREATE INDEX IF NOT EXISTS idx_base_canvas_land_development_category "
            f"ON {table_name} (land_development_category)"
        )
        return [gist_idx, btree_idx]

    @classmethod
    def group_by_aggregation_hint(cls) -> dict[str, list[str]]:
        """Return ``{hint: [column_names]}`` for all non-geometry, non-identity columns."""
        groups: dict[str, list[str]] = {}
        for col_def in cls._COLUMNS.values():
            if col_def.metatype in ("identity", "geometry"):
                continue
            groups.setdefault(col_def.aggregation_hint, []).append(col_def.name)
        return groups

    @classmethod
    def sum_columns(cls) -> list[str]:
        """Columns that should be area-weighted summed during spatial allocation."""
        return cls.group_by_aggregation_hint().get("sum", [])

    @classmethod
    def avg_columns(cls) -> list[str]:
        """Columns that should be area-weighted averaged during spatial allocation."""
        return cls.group_by_aggregation_hint().get("avg", [])

    @classmethod
    def by_metatype(cls, metatype: str) -> list[str]:
        """Return column names matching the given metatype."""
        return [
            col_def.name
            for col_def in cls._COLUMNS.values()
            if col_def.metatype == metatype
        ]
