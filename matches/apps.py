from django.apps import AppConfig


class MatchesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'matches'
    
    def ready(self):
        """Import signal handlers when app is ready"""
        import matches.signals  # noqa