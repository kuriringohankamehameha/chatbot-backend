from __future__ import absolute_import
import os
from celery import Celery
from celery.schedules import crontab
from django.conf import settings

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'chatbot.settings')

celery_app = Celery('chatbot')
celery_app.config_from_object(settings, namespace='CELERY')
celery_app.autodiscover_tasks(lambda: settings.INSTALLED_APPS)
