from django.apps import AppConfig


class WorkspaceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "brewgis.workspace"

    def ready(self) -> None:
        # Publishes map events when layers and background runs change.
        from brewgis.workspace import signals  # noqa: F401
