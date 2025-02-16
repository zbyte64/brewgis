

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

from brewgis.contrib.footprint.built_form.agriculture.agriculture_attribute_set import AgricultureAttributeSet
from brewgis.contrib.footprint.built_form.placetype import Placetype
from brewgis.contrib.footprint.built_form.built_form import BuiltForm

__author__ = 'calthorpe_analytics'
logger = logging.getLogger(__name__)

# noinspection PySingleQuotedDocstring
class LandscapeType(Placetype, AgricultureAttributeSet):
    """
    Placetypes are a set of BuildingTypes with a percent mix applied to each BuildingType
    """
    

    # So the model is pluralized correctly in the admin.
    class Meta(BuiltForm.Meta):
        verbose_name_plural = "Landscape Types"
        app_label = 'main'
