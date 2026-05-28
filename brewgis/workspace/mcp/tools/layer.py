"""MCP tools for layer CRUD, symbology, and filter operations."""

import logging
from typing import Any

from django.db import connection
from django.shortcuts import get_object_or_404
from pydantic import BaseModel

from brewgis.workspace.models import Layer
from brewgis.workspace.models import LayerFilter
from brewgis.workspace.models import SymbologyConfig
from brewgis.workspace.models import Workspace
from brewgis.workspace.services.column_inspector import get_table_schema
from brewgis.workspace.symbology.auto import auto_generate_symbology
from brewgis.workspace.symbology.generator import generate_maplibre_style

logger = logging.getLogger(__name__)


# ── Output Schemas ────────────────────────────────────────────


class LayerSummary(BaseModel):
    key: str
    name: str
    geometry_type: str
    feature_count: int | None
    symbology_type: str | None


class ColumnInfo(BaseModel):
    name: str
    data_type: str
    nullable: bool
    sample_values: list[Any]


class SymbologyConfigSchema(BaseModel):
    symbology_type: str
    default_color: str
    default_opacity: float
    palette_name: str
    attribute_column: str | None
    num_classes: int
    classes: list[dict[str, Any]]
    null_color: str | None
    zoom_min: float | None
    zoom_max: float | None


# ── Tool Registration ─────────────────────────────────────────


def register_tools(server: object) -> None:
    """Register layer tools with the MCP server."""

    @server.tool()  # type: ignore[attr-defined]
    def list_layers(
        workspace_slug: str,
        scenario_slug: str | None = None,
    ) -> list[dict[str, Any]]:
        """List layers for a workspace, optionally scoped to a scenario."""
        try:
            ws_pk = int(workspace_slug)
        except ValueError:
            return []
        workspace = get_object_or_404(Workspace, pk=ws_pk)
        layers = Layer.objects.filter(workspace=workspace)
        results = []
        for layer in layers:
            feat_count = None
            try:
                qs = connection.ops.quote_name
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"SELECT COUNT(*) FROM {qs(workspace.db_schema)}.{qs(layer.db_table)}"
                    )
                    feat_count = cursor.fetchone()[0]
            except Exception:
                pass
            sym_type = None
            try:
                sym_type = layer.symbology.symbology_type
            except Exception:
                pass
            results.append(
                LayerSummary(
                    key=layer.key,
                    name=layer.name,
                    geometry_type=layer.geometry_type,
                    feature_count=feat_count,
                    symbology_type=sym_type,
                ).model_dump()
            )
        return results

    @server.tool()  # type: ignore[attr-defined]
    def get_layer_schema(workspace_slug: str, layer_key: str) -> dict[str, Any]:
        """Get column schema for a layer's backing PostGIS table."""
        try:
            ws_pk = int(workspace_slug)
        except ValueError:
            return {"error": "Invalid workspace slug"}
        workspace = get_object_or_404(Workspace, pk=ws_pk)
        layer = get_object_or_404(Layer, key=layer_key, workspace=workspace)

        try:
            schema = get_table_schema(workspace.db_schema, layer.db_table)
        except Exception as e:
            return {"error": f"Failed to read schema: {e}", "columns": []}

        columns = []
        for col in schema:
            columns.append(
                ColumnInfo(
                    name=col.get("name", ""),
                    data_type=col.get("data_type", "unknown"),
                    nullable=col.get("nullable", True),
                    sample_values=col.get("sample_values", []),
                ).model_dump()
            )
        return {"columns": columns}

    @server.tool()  # type: ignore[attr-defined]
    def query_layer_data(
        workspace_slug: str,
        layer_key: str,
        columns: list[str] | None = None,
        limit: int = 100,
        offset: int = 0,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Query rows from a layer's backing table."""
        try:
            ws_pk = int(workspace_slug)
        except ValueError:
            return {"error": "Invalid workspace slug", "rows": []}
        workspace = get_object_or_404(Workspace, pk=ws_pk)
        layer = get_object_or_404(Layer, key=layer_key, workspace=workspace)

        qs = connection.ops.quote_name
        schema = qs(workspace.db_schema)
        table = qs(layer.db_table)

        # Build column list
        if columns:
            col_expr = ", ".join(qs(c) for c in columns)
            col_expr += f", {qs('geometry')} AS geom"
        else:
            col_expr = "*"

        # Build WHERE clause
        where_clause = ""
        params: list[Any] = []
        if filters:
            clauses = []
            for col, val in filters.items():
                safe_col = qs(col)
                if isinstance(val, dict):
                    for op, v in val.items():
                        if op == "eq":
                            clauses.append(f"{safe_col} = %s")
                            params.append(v)
                        elif op == "neq":
                            clauses.append(f"{safe_col} != %s")
                            params.append(v)
                        elif op == "gt":
                            clauses.append(f"{safe_col} > %s")
                            params.append(v)
                        elif op == "lt":
                            clauses.append(f"{safe_col} < %s")
                            params.append(v)
                        elif op == "like":
                            clauses.append(f"{safe_col} LIKE %s")
                            params.append(f"%{v}%")
                else:
                    clauses.append(f"{safe_col} = %s")
                    params.append(val)
            if clauses:
                where_clause = " WHERE " + " AND ".join(clauses)

        sql = (
            f"SELECT {col_expr} FROM {schema}.{table}{where_clause} LIMIT %s OFFSET %s"
        )
        params.extend([limit, offset])

        try:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                rows = cursor.fetchall()
                return {
                    "count": len(rows),
                    "rows": [
                        dict(
                            zip(
                                [col[0] for col in cursor.description],
                                row,
                                strict=False,
                            )
                        )
                        for row in rows
                    ],
                }
        except Exception as e:
            return {"error": str(e), "rows": []}

    @server.tool()  # type: ignore[attr-defined]
    def get_symbology(workspace_slug: str, layer_key: str) -> dict[str, Any]:
        """Get symbology configuration for a layer."""
        try:
            ws_pk = int(workspace_slug)
        except ValueError:
            return {"error": "Invalid workspace slug"}
        workspace = get_object_or_404(Workspace, pk=ws_pk)
        layer = get_object_or_404(Layer, key=layer_key, workspace=workspace)
        try:
            config = layer.symbology
        except SymbologyConfig.DoesNotExist:
            return {"error": "No symbology config for this layer"}

        classes = []
        for cls in config.classes.all().order_by("sort_order"):
            classes.append(
                {
                    "label": cls.label,
                    "min_value": cls.min_value,
                    "color": cls.color,
                    "opacity": cls.opacity,
                    "sort_order": cls.sort_order,
                }
            )
        return SymbologyConfigSchema(
            symbology_type=config.symbology_type,
            default_color=config.default_color,
            default_opacity=config.default_opacity,
            palette_name=config.palette_name or "",
            attribute_column=config.attribute_column,
            num_classes=config.num_classes,
            classes=classes,
            null_color=config.null_color,
            zoom_min=config.min_zoom,
            zoom_max=config.max_zoom,
        ).model_dump()

    @server.tool()  # type: ignore[attr-defined]
    def list_layer_filters(workspace_slug: str, layer_key: str) -> list[dict[str, Any]]:
        """List saved filters for a layer."""
        try:
            ws_pk = int(workspace_slug)
        except ValueError:
            return []
        workspace = get_object_or_404(Workspace, pk=ws_pk)
        layer = get_object_or_404(Layer, key=layer_key, workspace=workspace)
        filters = LayerFilter.objects.filter(layer=layer)
        return [
            {
                "id": f.pk,
                "name": f.name,
                "filter_json": f.filter_json,
                "is_active": f.is_active,
            }
            for f in filters
        ]

    @server.tool()  # type: ignore[attr-defined]
    def update_symbology(
        workspace_slug: str,
        layer_key: str,
        symbology_type: str = "single",
        default_color: str = "#888888",
        default_opacity: float = 0.7,
        palette_name: str = "",
        attribute_column: str | None = None,
        num_classes: int = 5,
    ) -> dict[str, Any]:
        """Update symbology configuration for a layer."""
        try:
            ws_pk = int(workspace_slug)
        except ValueError:
            return {"error": "Invalid workspace slug"}
        workspace = get_object_or_404(Workspace, pk=ws_pk)
        layer = get_object_or_404(Layer, key=layer_key, workspace=workspace)
        config, _ = SymbologyConfig.objects.get_or_create(layer=layer)
        config.symbology_type = symbology_type
        config.default_color = default_color
        config.default_opacity = default_opacity
        config.palette_name = palette_name
        config.attribute_column = attribute_column or ""
        config.num_classes = num_classes
        config.save()
        return {"status": "updated", "symbology_type": symbology_type}

    @server.tool()  # type: ignore[attr-defined]
    def auto_generate_symbology_tool(
        workspace_slug: str,
        layer_key: str,
        method: str = "quantile",
        num_classes: int = 5,
        palette: str = "Blues",
    ) -> dict[str, Any]:
        """Auto-generate symbology using the classification engine."""
        try:
            ws_pk = int(workspace_slug)
        except ValueError:
            return {"error": "Invalid workspace slug"}
        workspace = get_object_or_404(Workspace, pk=ws_pk)
        layer = get_object_or_404(Layer, key=layer_key, workspace=workspace)
        try:
            config = auto_generate_symbology(
                layer,
                classification_method=method,
                num_classes=num_classes,
                palette_name=palette,
            )
            return {
                "status": "generated",
                "symbology_type": config.symbology_type if config else "unknown",
            }
        except Exception as e:
            return {"error": str(e)}

    @server.tool()  # type: ignore[attr-defined]
    def preview_symbology_style(
        workspace_slug: str, layer_key: str, symbology_type: str = "single"
    ) -> dict[str, Any]:
        """Preview the MapLibre GL Style JSON for a layer's symbology."""
        try:
            ws_pk = int(workspace_slug)
        except ValueError:
            return {"error": "Invalid workspace slug"}
        workspace = get_object_or_404(Workspace, pk=ws_pk)
        layer = get_object_or_404(Layer, key=layer_key, workspace=workspace)
        try:
            style = generate_maplibre_style(layer.symbology)
            return {"style": style}
        except Exception as e:
            return {"error": str(e)}

    @server.tool()  # type: ignore[attr-defined]
    def create_layer(
        workspace_slug: str,
        name: str,
        table_schema: str,
        table_name: str,
        geometry_type: str = "fill",
        key: str | None = None,
    ) -> dict[str, Any]:
        """Register an existing PostGIS table as a layer."""
        try:
            ws_pk = int(workspace_slug)
        except ValueError:
            return {"error": "Invalid workspace slug"}
        workspace = get_object_or_404(Workspace, pk=ws_pk)
        layer_key = key or name.lower().replace(" ", "_")
        layer = Layer.objects.create(
            workspace=workspace,
            key=layer_key,
            name=name,
            layer_source=name,
            db_table=table_name,
            geometry_type=geometry_type,
        )
        try:
            auto_generate_symbology(layer)
        except Exception:
            pass
        return {"key": layer.key, "name": layer.name, "pk": layer.pk}

    @server.tool()  # type: ignore[attr-defined]
    def delete_layer_tool(workspace_slug: str, layer_key: str) -> dict[str, Any]:
        """Delete a layer."""
        try:
            ws_pk = int(workspace_slug)
        except ValueError:
            return {"error": "Invalid workspace slug", "deleted": False}
        workspace = get_object_or_404(Workspace, pk=ws_pk)
        layer = get_object_or_404(Layer, key=layer_key, workspace=workspace)
        layer.delete()
        return {"deleted": True, "key": layer_key}

    @server.tool()  # type: ignore[attr-defined]
    def create_filter(
        workspace_slug: str,
        layer_key: str,
        name: str,
        filter_json: str = "{}",
    ) -> dict[str, Any]:
        """Create a new filter for a layer."""
        try:
            ws_pk = int(workspace_slug)
        except ValueError:
            return {"error": "Invalid workspace slug"}
        workspace = get_object_or_404(Workspace, pk=ws_pk)
        layer = get_object_or_404(Layer, key=layer_key, workspace=workspace)
        f = LayerFilter.objects.create(
            layer=layer,
            name=name,
            filter_json=filter_json,
            is_active=True,
        )
        return {"id": f.pk, "name": f.name}

    @server.tool()  # type: ignore[attr-defined]
    def toggle_filter(
        workspace_slug: str,
        layer_key: str,
        filter_id: int,
        enabled: bool,
    ) -> dict[str, Any]:
        """Enable or disable a filter."""
        try:
            ws_pk = int(workspace_slug)
        except ValueError:
            return {"error": "Invalid workspace slug"}
        workspace = get_object_or_404(Workspace, pk=ws_pk)
        get_object_or_404(Layer, key=layer_key, workspace=workspace)
        f = get_object_or_404(LayerFilter, pk=filter_id)
        f.is_active = enabled
        f.save()
        return {"id": f.pk, "is_active": f.is_active}

    @server.tool()  # type: ignore[attr-defined]
    def delete_filter_tool(
        workspace_slug: str,
        layer_key: str,
        filter_id: int,
    ) -> dict[str, Any]:
        """Delete a filter."""
        try:
            ws_pk = int(workspace_slug)
        except ValueError:
            return {"error": "Invalid workspace slug"}
        workspace = get_object_or_404(Workspace, pk=ws_pk)
        get_object_or_404(Layer, key=layer_key, workspace=workspace)
        f = get_object_or_404(LayerFilter, pk=filter_id)
        f.delete()
        return {"deleted": True, "id": filter_id}
