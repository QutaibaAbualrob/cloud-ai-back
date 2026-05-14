from django.apps import AppConfig


class ApisConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apis'

    def ready(self):
        """
        Register signal handlers when the app is loaded.

        The import is inside ready() so that models are fully initialised
        before the signal receiver module is imported.
        """
        import apis.signals  # noqa: F401
