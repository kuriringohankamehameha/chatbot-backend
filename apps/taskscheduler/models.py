from django.db import models
from django.conf import settings
import uuid
import jsonfield

# Create your models here.

class ScheduleTask(models.Model):
    sched_hash = models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    title = models.CharField(null=True, max_length=100)

    created_on = models.DateTimeField(auto_now_add=True)
    scheduled_on = models.DateTimeField(null=True)
    scheduler_tz = models.CharField(default="UTC", null=True, max_length=100)
