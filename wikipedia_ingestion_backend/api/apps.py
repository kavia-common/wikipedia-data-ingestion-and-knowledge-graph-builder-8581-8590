from django.apps import AppConfig


class ApiConfig(AppConfig):
    """
    App configuration for the API app.
    """
    default_auto_field = "django.db.models.BigAutoField"
    # Keep the short app name to match INSTALLED_APPS and existing imports
    name = "api"
    verbose_name = "Wikipedia Ingestion API"
