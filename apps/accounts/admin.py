from django.contrib import admin

from .models import User, Teams

admin.site.register(Teams)
admin.site.register(User)

