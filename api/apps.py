from django.apps import AppConfig


class ApiConfig(AppConfig):
    """
    Home for cross-cutting concerns (finding ``L-4``).

    The app owns no models — it holds the health endpoint and the project-wide
    deployment checks, which need an app to be registered from.
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "api"

    def ready(self):
        from . import checks  # noqa: F401  (registers system checks)
