
from django.contrib import admin
from .models import PermissionRouting



@admin.register(PermissionRouting)
class PermissionRoutingAdmin(admin.ModelAdmin):
    pass
