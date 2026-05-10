from django.conf import settings
from django.db import models
from django.utils.text import slugify
import uuid

from brewgis.workspace.built_forms.models import BuildingType  # noqa: F401
from brewgis.workspace.built_forms.models import PlaceType  # noqa: F401
from brewgis.workspace.built_forms.models import PlaceTypeBuildingTypeMix  # noqa: F401
from brewgis.workspace.built_forms.models import StreetPatternChoices  # noqa: F401
from brewgis.workspace.built_forms.models import VintageChoices  # noqa: F401


class Workspace(models.Model):
    name = models.CharField(max_length=128)
    db_connection = models.CharField(max_length=64, default="default")
    db_schema = models.CharField(max_length=64, default="public")
    county_fips_list = models.JSONField(
        default=list,
        blank=True,
        help_text="List of {state, county} FIPS objects for multi-county workspaces.",
    )

    def __str__(self) -> str:
        return self.name


class Layer(models.Model):
    key = models.CharField(max_length=128)
    name = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="layers",
    )
    geometry_type = models.CharField(
        max_length=16,
        choices=[
            ("fill", "Fill (Polygon)"),
            ("line", "Line (Linestring)"),
            ("circle", "Circle (Point)"),
        ],
        default="fill",
        help_text="Derived from the source geometry type; can be overridden.",
    )
    display_order = models.IntegerField(default=0)
    layer_source = models.CharField(max_length=255)
    db_table = models.CharField(
        max_length=64,
    )  # TODO ask tipg or pg for list of options

    group = models.ForeignKey(
        "LayerGroup",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="layers",
    )

    class Meta:
        ordering = ("display_order",)
        unique_together = [("workspace", "key")]

    def __str__(self) -> str:
        return self.name

    def _source_id(self) -> str:
        """Return the tile server source identifier (schema.table)."""
        return f"{self.workspace.db_schema}.{self.db_table}"

    def resolve_tiles_url(self, tile_matrix_set: str = "WebMercatorQuad") -> str:
        """Return the raw tile URL template (tipg only; for backward compat)."""
        if settings.TILE_SERVER_BACKEND == "martin":
            return f"/martin/{self._source_id()}"
        return f"/tipg/collections/{self._source_id()}/tiles/{tile_matrix_set}"

    def to_maplibre_source(self) -> dict:
        """Return a MapLibre GL JS source specification dict."""
        if settings.TILE_SERVER_BACKEND == "martin":
            return {
                "type": "vector",
                "url": f"/martin/{self._source_id()}",
            }
        return {
            "type": "vector",
            "tiles": [
                f"/tipg/collections/{self._source_id()}/tiles/WebMercatorQuad/{{z}}/{{x}}/{{y}}"
            ],
        }


class SymbologyConfig(models.Model):
    layer = models.OneToOneField(
        Layer,
        on_delete=models.CASCADE,
        related_name="symbology",
    )
    symbology_type = models.CharField(
        max_length=16,
        choices=[
            ("single", "Single Symbol"),
            ("categorical", "Categorical"),
            ("graduated", "Graduated / Quantitative"),
        ],
        default="single",
    )
    attribute_column = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Feature column to style on (for categorical/graduated).",
    )
    default_color = models.CharField(max_length=16, default="#888888")
    default_opacity = models.FloatField(default=0.7)
    stroke_color = models.CharField(max_length=16, blank=True, default="")
    stroke_width = models.FloatField(default=1.0)
    line_width = models.FloatField(default=1.0)
    circle_radius = models.FloatField(default=4.0)
    palette_name = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="Named palette from palettes registry (blank = manual).",
    )
    reverse_palette = models.BooleanField(default=False)
    num_classes = models.IntegerField(default=5)
    classification_method = models.CharField(
        max_length=32,
        choices=[
            ("natural_breaks", "Natural Breaks (Jenks)"),
            ("equal_interval", "Equal Interval"),
            ("quantile", "Quantile"),
            ("jenks", "Jenks"),
            ("logarithmic", "Logarithmic"),
            ("std_deviation", "Standard Deviation"),
            ("manual", "Manual"),
        ],
        default="quantile",
    )
    null_handling = models.CharField(
        max_length=16,
        choices=[
            ("hide", "Hide nulls"),
            ("gray", "Gray (#cccccc)"),
            ("custom_color", "Custom color"),
        ],
        default="gray",
    )
    null_color = models.CharField(max_length=16, blank=True, default="")
    zero_transparent = models.BooleanField(
        default=False,
        help_text="Make zero-values fully transparent.",
    )
    auto_generated = models.BooleanField(
        default=True,
        help_text="Was this auto-generated from column statistics?",
    )
    min_zoom = models.FloatField(
        default=0.0,
        help_text="Minimum zoom level at which this layer is visible (MapLibre minzoom).",
    )
    max_zoom = models.FloatField(
        default=22.0,
        help_text="Maximum zoom level at which this layer is visible (MapLibre maxzoom).",
    )

    def __str__(self) -> str:
        return f"Symbology for {self.layer.name}"


class StyleClass(models.Model):
    symbology = models.ForeignKey(
        SymbologyConfig,
        on_delete=models.CASCADE,
        related_name="classes",
    )
    label = models.CharField(max_length=255)
    min_value = models.FloatField(blank=True, null=True)
    max_value = models.FloatField(blank=True, null=True)
    color = models.CharField(max_length=16, default="#888888")
    opacity = models.FloatField(blank=True, null=True)
    stroke_color = models.CharField(max_length=16, blank=True, default="")
    stroke_width = models.FloatField(blank=True, null=True)
    sort_order = models.IntegerField(default=0)

    class Meta:
        ordering = ("sort_order",)

    def __str__(self) -> str:
        return f"{self.label} ({self.symbology.layer.name})"


class ScenarioType(models.TextChoices):
    BASE = "base", "Base"
    ALTERNATIVE = "alternative", "Alternative"


class Scenario(models.Model):
    name = models.CharField(max_length=128)
    slug = models.SlugField(max_length=128)
    description = models.TextField(blank=True, default="")
    workspace = models.ForeignKey(
        Workspace, on_delete=models.CASCADE, related_name="scenarios"
    )
    scenario_type = models.CharField(
        max_length=16,
        choices=ScenarioType,
        default=ScenarioType.BASE,
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="alternatives",
    )
    base_year = models.IntegerField()
    horizon_year = models.IntegerField()
    schema_name = models.CharField(max_length=128, blank=True, default="")
    published = models.BooleanField(default=False, help_text="Make this scenario publicly viewable.")
    public_token = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        null=True,
        blank=True,
        help_text="UUID token for public sharing link.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("workspace", "slug")
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return self.name

    def save(self, *args: object, **kwargs: object) -> None:
        if not self.slug:
            self.slug = slugify(self.name)[:128]
        if not self.schema_name:
            self.schema_name = f"scenario_{self.slug}"
        super().save(*args, **kwargs)

    def delete(self, *args: object, **kwargs: object) -> None:
        """Drop the canvas view then delete the model."""
        from brewgis.workspace.services.canvas_view_manager import drop_canvas_view

        try:
            drop_canvas_view(self)
        except Exception:  # noqa: BLE001
            pass  # view may not exist
        super().delete(*args, **kwargs)

    @property
    def target_schema(self) -> str:
        return self.schema_name or f"scenario_{self.slug}"


class PaintedCanvas(models.Model):
    """Stores per-feature, per-column overrides for a scenario (EAV pattern).

    Each row represents one overridden column on one feature/parcel
    within a scenario.  The canvas SQL view pivots these rows and
    COALESCEs them over the base canvas table, implementing
    copy-on-write for tile server consumption.
    """

    scenario = models.ForeignKey(
        Scenario, on_delete=models.CASCADE, related_name="painted_features"
    )
    feature_id = models.CharField(max_length=128)
    column_name = models.CharField(max_length=128)
    painted_value = models.FloatField(null=True, blank=True)
    painted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True
    )
    painted_at = models.DateTimeField(auto_now_add=True)
    approval_status = models.CharField(
        max_length=16,
        choices=[
            ("pending", "Pending"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
        ],
        default="pending",
        help_text="Approval status for merge operations.",
    )

    class Meta:
        unique_together = ("scenario", "feature_id", "column_name")
        indexes = [
            models.Index(fields=["scenario", "feature_id"]),
        ]

    def __str__(self) -> str:
        return f"PaintedCanvas[{self.scenario_id}]({self.feature_id}.{self.column_name}={self.painted_value})"


class AnalysisRun(models.Model):
    """Tracks execution history of dbt analysis modules."""

    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="analysis_runs",
    )
    scenario = models.ForeignKey(
        Scenario,
        on_delete=models.CASCADE,
        related_name="analysis_runs",
    )
    modules = models.JSONField(
        default=list,
        help_text="List of module names executed (e.g. ['env_constraint', 'core']).",
    )
    status = models.CharField(
        max_length=16,
        choices=[
            ("pending", "Pending"),
            ("running", "Running"),
            ("completed", "Completed"),
            ("failed", "Failed"),
        ],
        default="pending",
    )
    vars = models.JSONField(
        default=dict,
        blank=True,
        help_text="dbt variables used for this run.",
    )
    column_mapping = models.JSONField(
        blank=True,
        default=dict,
        help_text="User-specified column name mappings (e.g. {'pop': 'population'}).",
    )
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    error_log = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "Analysis Run"

    def __str__(self) -> str:
        modules_str = ", ".join(self.modules) if self.modules else "unknown"
        return f"AnalysisRun #{self.pk} [{self.status}] ({modules_str})"


class DataImportRun(models.Model):
    """Tracks execution of data import operations (Census, LEHD, POI)."""

    IMPORT_TYPE_CHOICES = [
        ("allocate", "Spatial Allocation"),
        ("census", "Census ACS Demographics"),
        ("ejscreen", "EJScreen Environmental Justice"),
        ("health_rankings", "County Health Rankings"),
        ("lehd", "LEHD Employment"),
        ("parkserve", "ParkServe Park Data"),
        ("poi", "Points of Interest"),
        ("stitch", "Column Stitching"),
        ("svi", "Social Vulnerability Index"),
    ]

    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="data_import_runs",
    )
    import_type = models.CharField(
        max_length=16,
        choices=IMPORT_TYPE_CHOICES,
    )
    params = models.JSONField(
        default=dict,
        blank=True,
        help_text="Parameters for the import (FIPS codes, bounding box, etc.).",
    )
    result = models.JSONField(
        default=dict,
        blank=True,
        help_text="Result metadata (layer key, table name, row count, etc.).",
    )
    status = models.CharField(
        max_length=16,
        choices=[
            ("pending", "Pending"),
            ("running", "Running"),
            ("completed", "Completed"),
            ("failed", "Failed"),
        ],
        default="pending",
    )
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    error_log = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "Data Import Run"

    def __str__(self) -> str:
        return f"DataImportRun #{self.pk} [{self.import_type}] ({self.status})"



class POICache(models.Model):
    """GeoJSON cache of last successful POI fetch for offline fallback."""
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="poi_caches",
    )
    name = models.CharField(
        max_length=128,
        help_text="Cache identifier (e.g. 'food_poi').",
    )
    geojson_data = models.JSONField(
        help_text="GeoJSON FeatureCollection of POI data.",
    )
    source = models.CharField(
        max_length=64,
        default="osm",
        help_text="Original data source.",
    )
    fetched_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("workspace", "name")
        verbose_name = "POI Cache"

    def __str__(self) -> str:
        return f"POICache[{self.workspace_id}]({self.name})"



class ConstraintOperator(models.TextChoices):
    LT = "lt", "<"
    LTE = "lte", "<="
    GT = "gt", ">"
    GTE = "gte", ">="
    EQ = "eq", "="
    NEQ = "neq", "!="
    NOT_NULL = "not_null", "Not Null"


class ConstraintSeverity(models.TextChoices):
    BLOCK = "block", "Block"
    WARN = "warn", "Warn"


class PaintConstraint(models.Model):
    """Workspace-level rule governing allowed values on paintable columns."""

    workspace = models.ForeignKey(
        Workspace, on_delete=models.CASCADE, related_name="paint_constraints"
    )
    column = models.CharField(max_length=128)
    operator = models.CharField(max_length=16, choices=ConstraintOperator)
    value = models.FloatField(null=True, blank=True)
    message = models.TextField(blank=True, default="")
    severity = models.CharField(
        max_length=8,
        choices=ConstraintSeverity,
        default=ConstraintSeverity.BLOCK,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("column", "operator", "value")
        verbose_name = "Paint Constraint"
        verbose_name_plural = "Paint Constraints"


class MergeAudit(models.Model):
    """Audit trail for paint merge operations between scenarios.

    Records each merge operation: source scenario, target scenario,
    number of rows copied, and who performed it.
    """

    workspace = models.ForeignKey(
        Workspace, on_delete=models.CASCADE, related_name="merge_audits"
    )
    source_scenario = models.ForeignKey(
        Scenario, on_delete=models.CASCADE, related_name="source_merges"
    )
    target_scenario = models.ForeignKey(
        Scenario, on_delete=models.CASCADE, related_name="target_merges"
    )
    rows_copied = models.IntegerField(default=0)
    rows_skipped = models.IntegerField(default=0)
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "Merge Audit"

    def __str__(self) -> str:
        return (
            f"MergeAudit #{self.pk}: {self.source_scenario_id} → "
            f"{self.target_scenario_id} ({self.rows_copied} copied, "
            f"{self.rows_skipped} skipped)"
        )


class PaintEvent(models.Model):
    """Logs every paint operation for undo/redo support.

    Each row represents one column change on one feature/parcel
    within a scenario. A batch of events (same user, same action
    across multiple features) shares a ``batch_id`` for batch undo.
    """

    OPERATION_CHOICES = [
        ("paint", "Paint"),
        ("clear", "Clear"),
        ("built_form", "Built Form Paint"),
        ("undo", "Undo"),
    ]

    scenario = models.ForeignKey(
        Scenario, on_delete=models.CASCADE, related_name="paint_events"
    )
    feature_id = models.CharField(max_length=128)
    column_name = models.CharField(max_length=128)
    old_value = models.FloatField(null=True, blank=True)
    new_value = models.FloatField(null=True, blank=True)
    painted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True
    )
    painted_at = models.DateTimeField(auto_now_add=True, db_index=True)
    operation_type = models.CharField(max_length=16, choices=OPERATION_CHOICES)
    batch_id = models.CharField(max_length=64, db_index=True)
    undone_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-painted_at"]
        indexes = [
            models.Index(fields=["scenario", "-painted_at"]),
            models.Index(fields=["batch_id"]),
        ]
        verbose_name = "Paint Event"
        verbose_name_plural = "Paint Events"

    def __str__(self) -> str:
        op = self.get_operation_type_display()
        return (
            f"PaintEvent[{self.scenario_id}]({op}: "
            f"{self.feature_id}.{self.column_name} "
            f"{self.old_value}→{self.new_value})"
        )


class ScenarioReport(models.Model):
    """Tracks and stores generated reports (scenario comparison, paint tracking, map export)."""

    class ReportType(models.TextChoices):
        SCENARIO_COMPARISON = "scenario_comparison", "Scenario Comparison"
        PAINT_TRACKING = "paint_tracking", "Paint Tracking"
        MAP_EXPORT = "map_export", "Map Export"

    class ReportStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    workspace = models.ForeignKey(
        "Workspace", on_delete=models.CASCADE, related_name="reports"
    )
    scenario = models.ForeignKey(
        "Scenario", on_delete=models.SET_NULL, null=True, blank=True, related_name="reports"
    )
    name = models.CharField(max_length=255)
    report_type = models.CharField(max_length=32, choices=ReportType.choices)
    status = models.CharField(
        max_length=16, choices=ReportStatus.choices, default=ReportStatus.PENDING
    )
    report_file = models.FileField(upload_to="reports/", null=True, blank=True)
    error_log = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True
    )
    export_options = models.JSONField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Scenario Report"
        verbose_name_plural = "Scenario Reports"

    def __str__(self) -> str:
        return f"{self.get_report_type_display()}: {self.name} ({self.status})"

class County(models.Model):
    """US County FIPS lookup table, seeded from Census reference data."""

    state_fips = models.CharField(max_length=2)
    county_fips = models.CharField(max_length=3)
    name = models.CharField(max_length=128)

    class Meta:
        verbose_name_plural = "Counties"
        unique_together = ("state_fips", "county_fips")
        ordering = ("state_fips", "county_fips")

    def __str__(self) -> str:
        return f"{self.name} (FIPS {self.state_fips}{self.county_fips})"

class DataSourceCategory(models.Model):
    name = models.CharField(max_length=64, unique=True)
    slug = models.SlugField(max_length=64, unique=True)
    description = models.TextField(blank=True, default="")
    icon = models.CharField(max_length=64, blank=True, default="")
    sort_order = models.IntegerField(default=0)

    class Meta:
        ordering = ("sort_order", "name")
        verbose_name_plural = "Data Source Categories"

    def __str__(self) -> str:
        return self.name


class DataSource(models.Model):
    class FormatChoices(models.TextChoices):
        PARQUET = "parquet", "GeoParquet"
        SHAPEFILE = "shapefile", "Shapefile"
        GEOJSON = "geojson", "GeoJSON"
        GEOTIFF = "geotiff", "GeoTIFF"
        CSV = "csv", "CSV"
        API = "api", "REST API"
        WMS = "wms", "WMS"
        GTFS = "gtfs", "GTFS"

    class UpdateChoices(models.TextChoices):
        ANNUAL = "annual", "Annual"
        QUARTERLY = "quarterly", "Quarterly"
        SEMI_ANNUAL = "semi_annual", "Semi-annual"
        CONTINUOUS = "continuous", "Continuous"
        PERIODIC = "periodic", "Periodic"
        BIENNIAL = "biennial", "Biennial"
        FIVE_YEAR = "five_year", "5-Year"
        TEN_YEAR = "ten_year", "10-Year"

    class AcquisitionChoices(models.TextChoices):
        P0 = "p0", "P0 - Ship Now"
        P1 = "p1", "P1 - Phase 1"
        P2 = "p2", "P2 - Phase 2"

    category = models.ForeignKey(
        DataSourceCategory, on_delete=models.CASCADE, related_name="sources"
    )
    name = models.CharField(max_length=128)
    slug = models.SlugField(max_length=128, unique=True)
    description = models.TextField(blank=True, default="")
    provider = models.CharField(max_length=128)
    provider_url = models.URLField(max_length=512, blank=True, default="")
    data_format = models.CharField(max_length=16, choices=FormatChoices, blank=True, default="")
    update_frequency = models.CharField(max_length=16, choices=UpdateChoices, blank=True, default="")
    acquisition_priority = models.CharField(max_length=4, choices=AcquisitionChoices, blank=True, default="")
    icon = models.CharField(max_length=64, blank=True, default="")
    import_type = models.CharField(max_length=16, blank=True, default="", help_text="Maps to DataImportRun type")
    is_importable = models.BooleanField(default=False)
    sort_order = models.IntegerField(default=0)

    class Meta:
        ordering = ("category__sort_order", "sort_order", "name")
        verbose_name = "Data Source"

    def __str__(self) -> str:
        return f"{self.name} ({self.category.name})"

class LayerFilter(models.Model):
    """A saved filter expression for a layer.

    Stores an expression tree in JSON format that can be applied to filter
    features displayed on the map. Supports column filters, geometry filters,
    join filters, and AND/OR composition.
    """

    layer = models.ForeignKey(
        Layer,
        on_delete=models.CASCADE,
        related_name="filters",
    )
    name = models.CharField(max_length=255, blank=False)
    filter_json = models.JSONField(
        default=dict,
        blank=True,
        help_text="Expression tree: {\"type\": \"group\", \"operator\": \"AND\"|\"OR\", \"children\": [...]}",
    )
    is_active = models.BooleanField(
        default=False,
        help_text="When active, this filter is applied to the layer on the map.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)
        verbose_name = "Layer Filter"
        verbose_name_plural = "Layer Filters"

    def __str__(self) -> str:
        return f"{self.name} ({self.layer.name})"


class LayerGroup(models.Model):
    """A logical grouping of layers within a workspace."""

    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="layer_groups",
    )
    name = models.CharField(max_length=128)
    display_order = models.IntegerField(default=0)

    class Meta:
        ordering = ("display_order", "name")
        unique_together = [("workspace", "name")]

    def __str__(self) -> str:
        return self.name


class ExternalMapService(models.Model):
    """An external map service (WMS/WMTS/WFS/XYZ) added to a workspace."""

    class ServiceType(models.TextChoices):
        WMS = "wms", "WMS"
        WMTS = "wmts", "WMTS"
        WFS = "wfs", "WFS"
        XYZ = "xyz", "XYZ Tiles"

    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="external_services",
    )
    name = models.CharField(max_length=128)
    service_type = models.CharField(
        max_length=4,
        choices=ServiceType.choices,
        default=ServiceType.WMS,
    )
    url = models.URLField(max_length=1024)
    layers_param = models.CharField(
        max_length=512, blank=True, default="",
        help_text="Layers parameter for WMS (comma-separated)",
    )
    attribution = models.CharField(max_length=512, blank=True, default="")
    is_active = models.BooleanField(default=True)
    display_order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("display_order", "name")
        unique_together = [("workspace", "name")]
        verbose_name = "External Map Service"

    def __str__(self) -> str:
        return f"{self.name} ({self.get_service_type_display()})"

    def to_maplibre_source(self) -> dict:
        """Return a MapLibre GL JS source spec for this service."""
        if self.service_type in (self.ServiceType.WMS, self.ServiceType.WMTS, self.ServiceType.XYZ):
            if self.service_type == self.ServiceType.WMS:
                params = "?service=WMS&request=GetMap&layers=" + self.layers_param + "&format=image/png&transparent=true"
                return {
                    "type": "raster",
                    "tiles": [self.url + params + "&width=256&height=256&bbox={bbox-epsg-3857}"],
                    "attribution": self.attribution,
                    "tileSize": 256,
                }
            return {
                "type": "raster",
                "tiles": [self.url],
                "attribution": self.attribution,
                "tileSize": 256,
            }
        # WFS returns vector data — use as vector source
        return {
            "type": "vector",
            "tiles": [self.url],
            "attribution": self.attribution,
        }


class Basemap(models.Model):
    """A basemap style definition available for map rendering."""

    class TypeChoices(models.TextChoices):
        VECTOR = "vector", "Vector"
        RASTER = "raster", "Raster"

    name = models.CharField(max_length=128, unique=True)
    basemap_type = models.CharField(
        max_length=8,
        choices=TypeChoices.choices,
        default=TypeChoices.VECTOR,
    )
    style_url = models.URLField(
        max_length=1024, blank=True, default="",
        help_text="MapLibre style JSON URL (for vector basemaps)",
    )
    tile_url = models.URLField(
        max_length=1024, blank=True, default="",
        help_text="Tile URL template with {z}/{x}/{y} (for raster basemaps)",
    )
    attribution = models.CharField(max_length=512, blank=True, default="")
    thumbnail_url = models.URLField(max_length=1024, blank=True, default="")
    is_default = models.BooleanField(default=False)
    sort_order = models.IntegerField(default=0)

    class Meta:
        ordering = ("sort_order", "name")

    def __str__(self) -> str:
        return self.name

    def resolve_style(self) -> str | dict:
        """Return the MapLibre-compatible style value."""
        if self.basemap_type == self.TypeChoices.RASTER and self.tile_url:
            return {
                "version": 8,
                "sources": {
                    "basemap": {
                        "type": "raster",
                        "tiles": [self.tile_url],
                        "tileSize": 256,
                        "attribution": self.attribution,
                    },
                },
                "layers": [
                    {
                        "id": "basemap-layer",
                        "type": "raster",
                        "source": "basemap",
                        "minzoom": 0,
                        "maxzoom": 22,
                    },
                ],
            }
        return self.style_url