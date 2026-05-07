"""Template tags and filters for the workspace app."""
from __future__ import annotations

from django import template

register = template.Library()


@register.filter
def model_verbose_name(model_class: type) -> str:
    """Return the verbose_name of a model class.

    Usage in templates: ``{{ view.model|model_verbose_name|title }}``

    This avoids accessing ``_meta`` directly in templates, which Django's
    template engine forbids for attributes starting with underscore.
    """
    return model_class._meta.verbose_name  # noqa: SLF001
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
