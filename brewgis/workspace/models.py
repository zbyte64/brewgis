from django.db import models
from brewgis.workspace.built_forms.models import BuildingType  # noqa: F401
from brewgis.workspace.built_forms.models import PlaceType  # noqa: F401
from brewgis.workspace.built_forms.models import PlaceTypeBuildingTypeMix  # noqa: F401
from brewgis.workspace.built_forms.models import VintageChoices  # noqa: F401
from brewgis.workspace.built_forms.models import StreetPatternChoices  # noqa: F401


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

    def resolve_tiles_url(self, tile_matrix_set: str = "WebMercatorQuad") -> str:
        schema = self.workspace.db_schema
        return f"/tipg/collections/{schema}.{self.db_table}/tiles/{tile_matrix_set}"

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
