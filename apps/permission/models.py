from django.db import models
from django.conf import settings
from django.contrib.postgres.fields import JSONField


# Create your models here.
class PermissionRouting(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, related_name="permissionroutes", on_delete=models.CASCADE)
    routes = JSONField(db_column='routes', default=list, null=True)
    nav_routes = JSONField(db_column='nav_routes', default=list, null=True)



