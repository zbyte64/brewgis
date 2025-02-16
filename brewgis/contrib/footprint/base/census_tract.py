
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


from brewgis.contrib.footprint.geospatial.feature import Feature

__author__ = 'calthorpe_analytics'

from django.db import models


class CensusTract(Feature):

    tract = models.CharField(max_length=50, null=True)
    aland10 = models.CharField(max_length=50, null=True)
    awater10 = models.CharField(max_length=50, null=True)
    county = models.CharField(max_length=50, null=True)

    

    @property
    def label(self):
        return self.tract

    class Meta:
        abstract = True
        app_label = 'main'
