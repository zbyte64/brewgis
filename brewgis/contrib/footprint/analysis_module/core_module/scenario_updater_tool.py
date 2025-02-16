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

import logging


from brewgis.contrib.footprint.analysis_module.analysis_tool import AnalysisTool
from brewgis.contrib.footprint.analysis_module.core_module.core_update_future_scenario import update_future_scenario
from brewgis.contrib.footprint.analysis_module.core_module.core_update_increment import update_increment_feature
from brewgis.contrib.footprint.geospatial.db_entity_keys import DbEntityKey
from brewgis.contrib.footprint.utils.query_parsing import annotated_related_feature_class_pk_via_geographies
from footprint.utils.websockets import send_message_to_client

logger = logging.getLogger(__name__)

class ScenarioUpdaterTool(AnalysisTool):

    

    class Meta(object):
        app_label = 'main'
        abstract = False

    def progress(self, proportion, **kwargs):
        send_message_to_client(
            kwargs['user'].id,
            dict(
                event='postSavePublisherProportionCompleted',
                job_id=str(kwargs['job'].hashid),
                config_entity_id=self.config_entity.id,
                ids=[kwargs['analysis_module'].id],
                class_name='AnalysisModule',
                key=kwargs['analysis_module'].key,
                proportion=proportion))

    def update(self, **kwargs):
        """
            :param: kwargs 'ids' is required. They contain the EndStateFeature ids
            that were updated
        """
        logger.info("Executing Scenario Updater (aka Core) using {0}".format(self.config_entity))

        # Get the EndState Feature ids
        ids = kwargs['ids']
        config_entity = kwargs['analysis_module'].config_entity
        feature_class = config_entity.db_entity_feature_class(DbEntityKey.END_STATE)
        features = feature_class.objects.filter(id__in=ids)
        annotated_features = annotated_related_feature_class_pk_via_geographies(features, config_entity, [
            DbEntityKey.INCREMENT,
            DbEntityKey.BASE_CANVAS])

        self.progress(0.33, **kwargs)
        update_future_scenario(self.config_entity, annotated_features)
        self.progress(0.33, **kwargs)
        update_increment_feature(self.config_entity, annotated_features)
        self.progress(0.34, **kwargs)

        logger.info("Executed Scenario Updater using {0}".format(self.config_entity))
