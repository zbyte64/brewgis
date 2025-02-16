# coding=utf-8

# UrbanFootprint v1.5
# Copyright (C) 2017 Calthorpe Analytics
#
# This file is part of UrbanFootprint version 1.5
#
# UrbanFootprint is distributed under the terms of the GNU General
# Public License version 3, as published by the Free Software Foundation. This
# code is distributed WITHOUT ANY WARRANTY, without implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General
# Public License v3 for more details; see <http://www.gnu.org/licenses/>.

# from constants import Constants

import logging

from django.core.exceptions import ImproperlyConfigured
from django.contrib import admin
from django.db import models

from south.modelsinspector import add_introspection_rules
add_introspection_rules([],  [r"^brewgis.contrib.footprint.config.model_pickled_object_field.ModelPickledObjectField",
                              r"^brewgis.contrib.footprint.config.model_pickled_object_field.SelectionModelsPickledObjectField"])

from brewgis.contrib.footprint.config.model_pickled_object_field import ModelPickledObjectField
from brewgis.contrib.footprint.config.model_pickled_object_field import SelectionModelsPickledObjectField

import geospatial

# These import statements are compulsory. Models will not be recognized without them
# There are some tricks published online to import all classes dynamically, but doing so in
# practice has yet been unsuccessful

from brewgis.contrib.footprint.geospatial.behavior import Behavior
from brewgis.contrib.footprint.analysis_module.analysis_module import AnalysisModule
from brewgis.contrib.footprint.analysis.agriculture_feature import AgricultureFeature

from brewgis.contrib.footprint.base.canvas_feature import CanvasFeature
from brewgis.contrib.footprint.analysis.core_increment_feature import CoreIncrementFeature
from brewgis.contrib.footprint.analysis.fiscal_feature import FiscalFeature
from brewgis.contrib.footprint.analysis.energy_feature import EnergyFeature
from brewgis.contrib.footprint.analysis.water_feature import WaterFeature
from brewgis.contrib.footprint.analysis.public_health_features.ph_variables_feature import \
    PhVariablesFeature
from brewgis.contrib.footprint.analysis.public_health_features.ph_grid_outcomes_feature import \
    PhGridOutcomesFeature
from brewgis.contrib.footprint.analysis.public_health_features.ph_block_group_outcomes_feature import \
    PhBlockGroupOutcomesFeature
from brewgis.contrib.footprint.analysis.vmt_features.vmt_feature import VmtFeature
from brewgis.contrib.footprint.analysis.vmt_features.vmt_variables_feature import VmtVariablesFeature
from brewgis.contrib.footprint.analysis.vmt_features.vmt_trip_lengths_feature import VmtTripLengthsFeature
from brewgis.contrib.footprint.analysis.climate_zone_feature import ClimateZoneFeature
from brewgis.contrib.footprint.database.information_schema import PGNamespace

from brewgis.contrib.footprint.analysis.climate_zone_feature import ClimateZoneFeature

from brewgis.contrib.footprint.built_form.built_form import BuiltForm
from brewgis.contrib.footprint.geospatial.db_entity import DbEntity
from brewgis.contrib.footprint.geospatial.behavior import Behavior
from brewgis.contrib.footprint.geospatial.feature_behavior import FeatureBehavior
from brewgis.contrib.footprint.config.config_entity import ConfigEntity

from brewgis.contrib.footprint.policy.energy.commercial_energy_baseline import CommercialEnergyBaseline
from brewgis.contrib.footprint.policy.energy.residential_energy_baseline import ResidentialEnergyBaseline
from brewgis.contrib.footprint.policy.water.evapotranspiration_baseline import EvapotranspirationBaseline

from brewgis.contrib.footprint.base.census_rates_feature import CensusRatesFeature
from brewgis.contrib.footprint.base.transit_stop_feature import TransitStopFeature

from brewgis.contrib.footprint.presentation.layer.layer import Layer
from brewgis.contrib.footprint.built_form.flat_built_form import FlatBuiltForm
from brewgis.contrib.footprint.base.census_blockgroup import CensusBlockgroup
from brewgis.contrib.footprint.base.census_block import CensusBlock
from brewgis.contrib.footprint.base.census_tract import CensusTract
from brewgis.contrib.footprint.analysis.public_health_features.ph_grid_feature import PhGridFeature
from brewgis.contrib.footprint.analysis.public_health_features.ph_outcomes_summary import PhOutcomesSummary

from brewgis.contrib.footprint.built_form.primary_component import PrimaryComponent
from brewgis.contrib.footprint.built_form.primary_component_percent import PrimaryComponentPercent
from brewgis.contrib.footprint.built_form.placetype_component import PlacetypeComponent
from brewgis.contrib.footprint.built_form.placetype_component_percent import PlacetypeComponentPercent
from brewgis.contrib.footprint.built_form.placetype import Placetype

from brewgis.contrib.footprint.built_form.urban.urban_placetype import UrbanPlacetype
from brewgis.contrib.footprint.built_form.urban.building_attribute_set import BuildingAttributeSet
from brewgis.contrib.footprint.built_form.urban.building_use_definition import BuildingUseDefinition
from brewgis.contrib.footprint.built_form.urban.building_use_percent import BuildingUsePercent
from brewgis.contrib.footprint.built_form.urban.building import Building
from brewgis.contrib.footprint.built_form.urban.building_type import BuildingType

from brewgis.contrib.footprint.built_form.agriculture.crop import Crop
from brewgis.contrib.footprint.built_form.agriculture.crop_type import CropType
from brewgis.contrib.footprint.built_form.agriculture.landscape_type import LandscapeType
from brewgis.contrib.footprint.built_form.agriculture.agriculture_attribute_set import AgricultureAttributeSet

from brewgis.contrib.footprint.config.db_entity_interest import DbEntityInterest

from brewgis.contrib.footprint.config.global_config import GlobalConfig
from brewgis.contrib.footprint.config.interest import Interest
from brewgis.contrib.footprint.config.policy_set import PolicySet
from brewgis.contrib.footprint.config.region import Region
from brewgis.contrib.footprint.config.project import Project
from brewgis.contrib.footprint.config.scenario import Scenario
from brewgis.contrib.footprint.base.canvas_feature import CanvasFeature
from brewgis.contrib.footprint.base.cpad_holdings_feature import CpadHoldingsFeature
from brewgis.contrib.footprint.geographies.geography import Geography
from brewgis.contrib.footprint.geographies.parcel import Parcel
from brewgis.contrib.footprint.geographies.grid_cell import GridCell
from brewgis.contrib.footprint.geographies.taz import Taz
from brewgis.contrib.footprint.presentation.chart import Chart
from brewgis.contrib.footprint.presentation.geo_library import GeoLibrary
from brewgis.contrib.footprint.presentation.geo_library_catalog import GeoLibraryCatalog
from brewgis.contrib.footprint.presentation.grid import Grid
from brewgis.contrib.footprint.presentation.layer_chart import LayerChart
from brewgis.contrib.footprint.presentation.layer_library import LayerLibrary
from brewgis.contrib.footprint.presentation.map import Map
from brewgis.contrib.footprint.presentation.medium import Medium
from brewgis.contrib.footprint.presentation.presentation import Presentation
from brewgis.contrib.footprint.presentation.presentation_medium import PresentationMedium
from brewgis.contrib.footprint.presentation.report import Report
from brewgis.contrib.footprint.presentation.result.result import Result
from brewgis.contrib.footprint.presentation.result_library import ResultLibrary
from brewgis.contrib.footprint.presentation.style import Style
from brewgis.contrib.footprint.presentation.layer_style import LayerStyle
from brewgis.contrib.footprint.presentation.presentation_configuration import PresentationConfiguration
from brewgis.contrib.footprint.sort_type import SortType
from brewgis.contrib.footprint.presentation.layer_selection import LayerSelection

from brewgis.contrib.footprint.analysis_module.public_health_module.public_health_updater_tool import PublicHealthOutcomeAnalysis

from brewgis.contrib.footprint.analysis_module.environmental_constraint_module.environmental_constraint_percent import \
    EnvironmentalConstraintPercent
from brewgis.contrib.footprint.analysis_module.environmental_constraint_module.environmental_constraint_updater_tool import \
    EnvironmentalConstraintUpdaterTool
from brewgis.contrib.footprint.analysis_module.merge_module.merge_updater_tool import MergeUpdaterTool
from brewgis.contrib.footprint.analysis_module.environmental_constraint_module.environmental_constraint_union_tool import EnvironmentalConstraintUnionTool

from brewgis.contrib.footprint.group_hierarchy import GroupHierarchy

logger = logging.getLogger(__name__)

# Enable generic browsing of all models exported above in the Django
# admin interface.  But first, make a copy of locals so we can iterate
# it without it changing.
_l = dict(locals())
for key, cls in _l.iteritems():
    try:
        if issubclass(cls, models.Model):
            admin.site.register(cls)
    except (ImproperlyConfigured, TypeError):
        # Ignore
        pass
    except Exception as e:
        logging.exception('Ignoring admin error')
        print "(Save to ignore, this is just for admin interface)"

# This is required to wire the adoption signals at startup.
# TODO move signals to a Django startup hook
import signals
