from django.urls import path
from django.utils.translation import gettext_lazy as _

from .models import Scenario
from .views import CreateLayerView, ReadGISFileView, view_scenario_map

from viewflow.urls import AppMenuMixin, ModelViewset, Viewset
from viewflow.utils import viewprop
from viewflow.views import Action


class ImportDataViewset(AppMenuMixin, Viewset):
    read_gis_file_view_class = ReadGISFileView

    @viewprop
    def read_gis_file_view(self):
        return self.read_gis_file_view_class.as_view()

    @property
    def index_path(self):
        return path("", self.read_gis_file_view, name="index")
    

class CreateLayerViewset(AppMenuMixin, Viewset):
    @property
    def index_path(self):
        return path("", CreateLayerView.as_view(), name="index")


class ScenarioModelViewSet(ModelViewset):
    model = Scenario
    update_page_actions = [Action(
        name='View Scenario on Map',
        url='../view-map/'
    )]

    @property
    def view_map_path(self):
        return path("<int:pk>/view-map/", view_scenario_map, name="view-map")
    

