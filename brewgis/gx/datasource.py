"""PostGIS Data Source factory for Great Expectations."""

from __future__ import annotations

import logging

import great_expectations as gx  # noqa: TC002

from brewgis.workspace.services._db import _database_url

logger = logging.getLogger(__name__)

__all__ = [
    "add_postgres_datasource",
]


def add_postgres_datasource(context: gx.DataContext) -> str:
    """Add (or retrieve) the ``brewgis_postgis`` Postgres datasource.

    Returns the datasource name (``"brewgis_postgis"``).
    """
    datasource_name = "brewgis_postgis"
    try:
        _ = context.data_sources.get(datasource_name)
        logger.debug("Datasource '%s' already exists", datasource_name)
    except KeyError:
        pass
    else:
        return datasource_name

    connection_string = _database_url()
    context.data_sources.add_postgres(
        name=datasource_name,
        connection_string=connection_string,
    )
    logger.info("Added Postgres datasource '%s'", datasource_name)
    return datasource_name
