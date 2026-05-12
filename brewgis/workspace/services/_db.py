"""Centralized database connection utility.

All modules requiring a SQLAlchemy engine SHOULD obtain it via :func:`get_engine`
and :func:`text` from this module instead of importing ``sqlalchemy`` directly.
"""

from __future__ import annotations

from functools import cache

from django.conf import settings
from sqlalchemy import Engine
from sqlalchemy import create_engine
from sqlalchemy import text  # noqa: F401 — re-exported for caller convenience


def _database_url() -> str:
    """Build a PostgreSQL connection URL from Django DATABASES settings.

    Works correctly under test because Django's test runner updates
    ``settings.DATABASES["default"]["NAME"]`` before tests begin.
    """
    db = settings.DATABASES["default"]
    return (
        f"postgresql://{db['USER']}:{db['PASSWORD']}"
        f"@{db['HOST']}:{db['PORT']}/{db['NAME']}"
    )


@cache
def get_engine() -> Engine:
    """Return a cached SQLAlchemy engine for the default database."""
    return create_engine(_database_url())
