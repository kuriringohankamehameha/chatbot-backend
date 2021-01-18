from django.apps import AppConfig
#from django.core.cache import cache

class TaskschedulerConfig(AppConfig):
    name = 'apps.taskscheduler'

    def ready(self):
        from apps.taskscheduler.schedule_manager import management
        management.start()
