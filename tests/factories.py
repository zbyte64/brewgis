"""Factory Boy factories for Brew GIS models."""

from __future__ import annotations

import factory
from django.contrib.auth.models import User

from brewgis.workspace.built_forms.models import BuildingType
from brewgis.workspace.built_forms.models import PlaceType
from brewgis.workspace.built_forms.models import PlaceTypeBuildingTypeMix
from brewgis.workspace.models import Layer
from brewgis.workspace.models import StyleClass
from brewgis.workspace.models import SymbologyConfig
from brewgis.workspace.models import Workspace
from brewgis.workspace.models import AnalysisRun


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User
        django_get_or_create = ("username",)
        skip_postgeneration_save = True

    username = factory.Sequence(lambda n: f"user_{n}")
    email = factory.LazyAttribute(lambda o: f"{o.username}@example.com")
    password = factory.PostGenerationMethodCall("set_password", "testpass123")

    @classmethod
    def _after_postgeneration(cls, instance, create, results=None):
        """Save after post-generation hooks to persist password hash."""
        super()._after_postgeneration(instance, create, results)
        if create:
            instance.save()


class WorkspaceFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Workspace

    name = factory.Sequence(lambda n: f"Workspace {n}")
    db_connection = "default"
    db_schema = "public"


class LayerFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Layer

    key = factory.Sequence(lambda n: f"layer_{n}")
    name = factory.Sequence(lambda n: f"Layer {n}")
    workspace = factory.SubFactory(WorkspaceFactory)
    db_table = factory.Sequence(lambda n: f"test_table_{n}")
    layer_source = factory.LazyAttribute(lambda o: f"test://{o.db_table}")
    geometry_type = "fill"


class SymbologyConfigFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = SymbologyConfig

    layer = factory.SubFactory(LayerFactory)


class StyleClassFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = StyleClass

    symbology = factory.SubFactory(SymbologyConfigFactory)
    label = factory.Sequence(lambda n: f"Class {n}")


class ScenarioFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "workspace.Scenario"

    name = factory.Sequence(lambda n: f"Scenario {n}")
    slug = factory.Sequence(lambda n: f"scenario-{n}")
    workspace = factory.SubFactory(WorkspaceFactory)
    base_year = 2020
    horizon_year = 2050


class AnalysisRunFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AnalysisRun

    workspace = factory.SubFactory(WorkspaceFactory)
    scenario = factory.SubFactory(
        ScenarioFactory,
        workspace=factory.SelfAttribute("..workspace"),
    )
    modules = ["env_constraint"]
    status = "pending"
    vars = {}


class PaintedCanvasFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "workspace.PaintedCanvas"

    scenario = factory.SubFactory(ScenarioFactory)
    feature_id = factory.Sequence(lambda n: f"feature-{n}")
    column_name = "du"
    painted_value = 100.0


class BuildingTypeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = BuildingType

    name = factory.Sequence(lambda n: f"Building Type {n}")
    du_per_acre = 10.0
    emp_per_acre = 0.0
    far = 0.8
    household_size = 2.5
    vacancy_rate = 5.0
    parking_sqft_per_space = 300.0
    pass_by_trip_pct = 0.0


class PlaceTypeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PlaceType

    name = factory.Sequence(lambda n: f"Place Type {n}")
    row_allocation_pct = 25.0


class PlaceTypeBuildingTypeMixFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PlaceTypeBuildingTypeMix

    place_type = factory.SubFactory(PlaceTypeFactory)
    building_type = factory.SubFactory(BuildingTypeFactory)
    percentage = 100.0
