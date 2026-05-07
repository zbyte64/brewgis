from django.conf import settings
from django.db import models
from django.utils.text import slugify

from brewgis.workspace.built_forms.models import BuildingType  # noqa: F401
from brewgis.workspace.built_forms.models import PlaceType  # noqa: F401
from brewgis.workspace.built_forms.models import PlaceTypeBuildingTypeMix  # noqa: F401
from brewgis.workspace.built_forms.models import StreetPatternChoices  # noqa: F401
from brewgis.workspace.built_forms.models import VintageChoices  # noqa: F401


class Workspace(models.Model):
    name = models.CharField(max_length=128)
    db_connection = models.CharField(max_length=64, default="default")
    db_schema = models.CharField(max_length=64, default="public")

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
        choices=ScenarioType.choices,
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
        return f"scenario_{self.slug}"


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
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
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
        ("census", "Census ACS Demographics"),
        ("lehd", "LEHD Employment"),
        ("poi", "Points of Interest"),
        ("allocate", "Spatial Allocation"),
        ("stitch", "Column Stitching"),
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
