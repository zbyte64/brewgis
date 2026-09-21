"""Template tags and filters for the workspace app."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from django import template
from django.template.defaultfilters import stringfilter
from django.utils import timezone

if TYPE_CHECKING:
    from datetime import datetime

register = template.Library()

_SECONDS_PER_MINUTE = 60
_MINUTES_PER_HOUR = 60


@register.filter
def model_verbose_name(model_class: object) -> str:
    """Return the verbose_name of a model class.

    Usage in templates: ``{{ view.model|model_verbose_name|title }}``

    This avoids accessing ``_meta`` directly in templates, which Django's
    template engine forbids for attributes starting with underscore.
    Handles both model classes and dotted string references.
    """
    if isinstance(model_class, str):
        from django.apps import apps

        if "." in model_class:
            try:
                model_class = apps.get_model(model_class)
            except LookupError:
                pass
        if isinstance(model_class, str):
            # Try to find the model by name across all registered apps
            for app_config in apps.get_app_configs():
                try:
                    model_class = app_config.get_model(model_class, require_ready=False)  # type: ignore[arg-type]
                    break
                except LookupError:
                    continue
    if isinstance(model_class, str):
        return model_class.split(".")[-1] if "." in model_class else model_class
    if hasattr(model_class, "_meta"):
        return model_class._meta.verbose_name  # type: ignore[no-any-return]  # noqa: SLF001
    return str(model_class)


@register.filter
def analysis_status_badge(status: str) -> str:
    """Return a Bootstrap badge class for an analysis run status."""
    badge_map = {
        "pending": "secondary",
        "running": "primary",
        "completed": "success",
        "failed": "danger",
    }
    return badge_map.get(status, "secondary")


@register.filter
def duration(start: datetime | None, end: datetime | None = None) -> str:
    """Human-readable elapsed time between two datetimes.

    Django's ``timesince`` rounds to whole minutes, which renders a
    21-second analysis run as "0 minutes" — useless when the whole point of
    showing a duration is telling a 20-second data error apart from a
    20-minute plan. ``end`` defaults to now, so a still-running run shows
    its time so far.
    """
    if start is None:
        return ""
    stop = end or timezone.now()
    seconds = max(0, int((stop - start).total_seconds()))
    if seconds < _SECONDS_PER_MINUTE:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, _SECONDS_PER_MINUTE)
    if minutes < _MINUTES_PER_HOUR:
        return f"{minutes}m {seconds}s"
    hours, minutes = divmod(minutes, _MINUTES_PER_HOUR)
    return f"{hours}h {minutes}m"


@register.filter
@stringfilter
def report_status_badge(status: str) -> str:
    """Return a Bootstrap badge class for a report generation status."""
    badge_map: dict[str, str] = {
        "pending": "secondary",
        "running": "primary",
        "completed": "success",
        "failed": "danger",
    }
    return badge_map.get(status, "secondary")


@register.filter
def dictlookup(d: dict | None, key: str | int) -> str:
    """Look up a key in a dictionary, returning "" if missing or not a dict.

    Tries the key as-is, then as int (for template-rendered numeric keys)
    and as string (for template-rendered string keys against int dict keys).

    Usage in templates: ``{{ data|dictlookup:"key" }}``
    """
    if not isinstance(d, dict):
        return ""
    # Try the key as-is
    if key in d:
        val = d[key]
        return str(val) if val is not None else ""
    # Try int (template renders ints as strings)
    try:
        ikey = int(key)
        if ikey in d:
            val = d[ikey]
            return str(val) if val is not None else ""
    except (ValueError, TypeError):
        pass
    # Try str (dict has string keys)
    skey = str(key)
    if skey in d:
        val = d[skey]
        return str(val) if val is not None else ""
    return ""


@register.filter
def list_index(lst: list, index: int | None) -> str:
    """Return the element at the given index, or "" if out of range."""
    if index is None:
        return ""
    if not isinstance(lst, (list, tuple)) or index < 0 or index >= len(lst):
        return ""
    return str(lst[index])


@register.filter
def json_attr(value: object) -> str:
    """Serialize to JSON, safe for embedding in an HTML attribute.

    Escapes single quotes (which would break ``attr='{{ value|json_attr }}'``)
    and strips null bytes that could truncate the attribute value.

    Usage: ``<div data-config='{{ config|json_attr }}'>``
    or       ``<brew-gis-map layers='{{ layer_data|json_attr }}'>``
    """
    raw = json.dumps(value, default=str)
    # Escape single quotes — HTML attribute delimiters,
    # and strip null bytes that truncate in some parsers.
    return raw.replace("'", "\\u0027").replace("\x00", "")


@register.filter
def sqlmesh_model_url(schema: str, table: str) -> str:
    """Deep link to a model's page in the sqlmesh UI data catalog.

    Usage: ``{{ c.schema|sqlmesh_model_url:c.table }}``
    """
    from brewgis.workspace.services.sqlmesh_tables import sqlmesh_model_ui_url

    return sqlmesh_model_ui_url(schema, table)


@register.filter
def filter_expression(filter_json: dict) -> str:
    """Human-readable rendering of a LayerFilter's expression tree.

    Usage: ``{{ flt.filter_json|filter_expression }}``
    """
    from brewgis.workspace.views.filter import _human_readable_expression

    return _human_readable_expression(filter_json)
