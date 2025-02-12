import math

from django.conf import settings
from django.db import models


class Workspace(models.Model):
    name = models.CharField(max_length=128)
    db_connection = models.CharField(max_length=64, default='default')
    db_schema = models.CharField(max_length=64, default='public')

    def __str__(self):
        return self.name


class Scenario(models.Model):
    # key?
    name = models.CharField(max_length=128)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name='scenarios')
    layers = models.ManyToManyField('Layer', through='ScenarioLayer')

    # unique_together = [('workspace')] #TODO
    def __str__(self):
        return self.name


# TODO MapLayer?
class Layer(models.Model):
    # TODO name or key?
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name='layers')
    mapbox_style = models.JSONField(blank=True, null=True)
    display_order = models.IntegerField(default=0)

    class Meta:
        ordering = ('display_order',)


class ScenarioLayer(models.Model):
    layer = models.ForeignKey(Layer, on_delete=models.CASCADE, related_name='scenario_layers')
    scenario = models.ForeignKey(Scenario, on_delete=models.CASCADE, related_name='scenario_layers')
    db_table = models.CharField(max_length=64) # TODO ask tipg or pg for list of options

    def resolve_tiles_url(self, tile_matrix_set:str='WebMercatorQuad'):
        return f'/tipg/collections/{self.layer.workspace.db_schema}.{self.db_table}/tiles/{tile_matrix_set}'


# TODO coercable w/ model inheritance
class UserDefinedViews(models.Model):
    """
        Track User Defined Views
    """
    workspace = models.ForeignKey(Workspace, on_delete=models.PROTECT)
    scenario = models.ForeignKey(Scenario, null=True, blank=True, on_delete=models.PROTECT)
    # The user who last updated the db_entity
    updater = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    updated = models.DateTimeField(auto_now=True)
    processed = models.DateTimeField(null=True, blank=True)
    module = models.CharField(max_length=256)
    config = models.JSONField()
    db_view_result = models.CharField(max_length=64)
