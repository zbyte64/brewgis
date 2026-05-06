from django.db import models


class Workspace(models.Model):
    name = models.CharField(max_length=128)
    db_connection = models.CharField(max_length=64, default="default")
    db_schema = models.CharField(max_length=64, default="public")

    def __str__(self):
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
    mapbox_style = models.JSONField(blank=True, null=True)
    display_order = models.IntegerField(default=0)
    layer_source = models.CharField(max_length=255)
    db_table = models.CharField(
        max_length=64,
    )  # TODO ask tipg or pg for list of options

    class Meta:
        ordering = ("display_order",)
        unique_together = [("workspace", "key")]

    def __str__(self):
        return self.name

    def resolve_tiles_url(self, tile_matrix_set: str = "WebMercatorQuad"):
        schema = self.workspace.db_schema
        return f"/tipg/collections/{schema}.{self.db_table}/tiles/{tile_matrix_set}"
