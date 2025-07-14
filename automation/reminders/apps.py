from django.apps import AppConfig


class RemindersConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'reminders'
    def ready(self):
        from django.conf import settings
        if settings.SCHEDULER_AUTOSTART:
            from .views import schedule_daemon_task
            try:
                schedule_daemon_task()
            except Exception as e:
                import logging
                logging.error(f"Failed to start schedule_daemon_task: {e}")