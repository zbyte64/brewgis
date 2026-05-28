# Hypothesis

Urban Planners and Data Scientists are steered towards "enterprise" solutions (ArcGIS, Carto) because the current open source offerings (QGIS, tipg) have a greater but different barrier to entry (capital or expertise). Data Scientists are becoming more sophisticated with managing various language environments and are even involved in cloud ops that most could handle a setup process that solely requires installing Docker. If we give these scientists a batteries included GIS Workspace that they can easily modify, then their adapativeness would be greater than most SaS offerings in most situations. However, if this only aims to be a Workspace for Data Scientists & Engineers, then its impact would be similar to QGIS; the real goal is to make it easier for the Data Scientist to engage their community by taking care of all the boilerplate without adding capital barriers.



## Requirements

* Integrated Map Vector Tile services directly from our datasets (via tipg or martin)
* Workspace with Layers and Scenarios
  * Workspace is a collection of tables/views in a database schema (ie public)
  * A Layer is an identifier with a style and other display settings associated.
  * A Scenario is an identifier with a mapping of Layers to tables/views.
* A minimal UI to manipulate and diplay the Workspace (as two different entry points)
* User Defined Views (and maybe dbt models?)
  * Data user can define a process that spawns to tables/views (in code, as a new API endpoint)
  * Authenticated user can associate specfic input layers to models (ie base model)
* Should be simple enough for a Data Engineer to modify and extend.
  * Few Django apps, one if possible
  * Javascript will be used, but make it as composable as possible (ie web components over Redux)


### Additional Considerations

There is a relationship between base and future scenarios. Updating the base scenario may enque future scenario updates.
A UDF could be multiplied across scenarios in a workspace, especially in the case of footprint anaysis.

A Workspace may maintain a common mapping of scenario layers, ie a base map parcel layer or a transport layer. And those layers may need to provide a certain base set of keys.

Builtforms allow for features to quickly have values assigned via an ordinal value and we should not expect incomming tables to have these defined. These values are highly corelated with the analysis offerings.
