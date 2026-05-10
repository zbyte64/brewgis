"""Template tags and filters for the workspace app."""

from __future__ import annotations

import json

from django import template
from django.template.defaultfilters import stringfilter

register = template.Library()

@register.filter
def model_verbose_name(model_class: object) -> str:
    """Return the verbose_name of a model class.

    Usage in templates: ``{{ view.model|model_verbose_name|title }}``

    This avoids accessing ``_meta`` directly in templates, which Django's
    template engine forbids for attributes starting with underscore.
    Handles both model classes and dotted string references.
    """
    if isinstance(model_class, str):
        from django.apps import apps  # noqa: PLC0415

        if "." in model_class:
            try:
                model_class = apps.get_model(model_class)
            except LookupError:
                pass
        if isinstance(model_class, str):
            # Try to find the model by name across all registered apps
            for app_config in apps.get_app_configs():
                try:
                    model_class = app_config.get_model(model_class, require_ready=False)
                    break
                except LookupError:
                    continue
    if isinstance(model_class, str):
        return model_class.split(".")[-1] if "." in model_class else model_class
    if hasattr(model_class, "_meta"):
        return model_class._meta.verbose_name  # noqa: SLF001
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
def dictlookup(d: dict | None, key: str) -> str:
    """Look up a key in a dictionary, returning "" if missing or not a dict.

    Usage in templates: ``{{ data|dictlookup:"key" }}``
    """
    if isinstance(d, dict):
        value = d.get(key, "")
        return str(value) if value is not None else ""
    return ""

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
