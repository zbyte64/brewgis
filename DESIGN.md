# Hypothesis

Urban Planners and Data Scientists are steered towards "enterprise" solutions (ArcGIS, Carto) because the current open source offerings (QGIS, tipg) have a greater but different barrier to entry (capital or expertise). Data Scientists are becoming more sophisticated with managing various language environments and are even involved in cloud ops that most could handle a setup process that solely requires installing Docker. If we give these scientists a batteries included GIS Workspace that they can easily modify, then their adapativeness would be greater than most SaS offerings in most situations. However, if this only aims to be a Workspace for Data Scientists & Engineers, then its impact would be similar to QGIS; the real goal is to make it easier for the Data Scientist to engage their community by taking care of all the boilerplate without adding capital barriers.

## Requirements

* Integrated Map Vector Tile services directly from our datasets (via tipg)
* Workspace with Layers and Scenarios
  * Workspace is a collection of tables/views in a database schema (ie public)
  * A Layer is an identifier with a style and other display settings associated.
  * A Scenario is an identifier with a mapping of Layers to tables/views.
* A minimal UI to manipulate and diplay the Workspace (as two different entry points)
* Spawn new SQL tabbles/views (and maybe dbt models?)
  * Data user can define a process that spawns to tables/views (in code, as a new API endpoint)
  * Authenticated user can associate specfic input layers to models (ie base model)
