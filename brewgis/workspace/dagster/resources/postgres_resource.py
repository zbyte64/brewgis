"""Dagster resource providing a SQLAlchemy engine for PostGIS access.

Provides a :class:`~dagster.ConfigurableResource` that exposes the
cached database engine from :mod:`brewgis.workspace.services._db`.
"""

from __future__ import annotations

from dagster import ConfigurableResource

from brewgis.workspace.services._db import get_engine


class PostgresResource(ConfigurableResource):
    """Dagster resource providing a SQLAlchemy engine for the PostGIS database.

    Usage in an asset::

        @asset
        def my_asset(context, postgres: PostgresResource):
            with postgres.engine.connect() as conn:
                result = conn.execute(text("SELECT count(*) FROM my_table"))
    """

    @property
    def engine(self):  # type: ignore[return]  # noqa: ANN201
        """Return the cached SQLAlchemy engine."""
        return get_engine()
