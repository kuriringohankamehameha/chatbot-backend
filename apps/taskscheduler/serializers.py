from rest_framework import serializers
from . import models
from django.core.cache import cache
# channel for testing
class WhatsappMakeScheduleListSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.ScheduleTask
        fields = ('sched_hash', 'title', 'wab_client', 'template_id', 'scheduled_flag', 'created_on', 'task_done', 'template_title', 'wab_title', 'scheduled_on', 'scheduler_tz', "scheduler_result", "template_type", "extra", "delete_flag","schedulers_success_rate")


class WhatsappMakeScheduleRegDetailSerializer(serializers.ModelSerializer):
    sched_hash = serializers.URLField(read_only=True)
    scheduled_on = serializers.DateTimeField()


    class Meta:
        model = models.ScheduleTask
        fields = ('sched_hash', 'title', 'wab_client', 'template_id', 'data', 'scheduled_on', 'task_done', 'owner', 'param_label', 'scheduled_flag', 'scheduler_tz', 'extra', "scheduler_result", 'created_on', 'template_title', 'wab_title', "template_type","schedulers_success_rate")
