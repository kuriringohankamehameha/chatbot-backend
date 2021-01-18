from django.contrib import admin
from django.urls import path, include, re_path
from django.conf.urls.static import static
from django.conf import settings

from django.views.decorators.csrf import csrf_exempt

from rest_framework import permissions
from drf_yasg.views import get_schema_view
from drf_yasg import openapi
from decouple import config


schema_view = get_schema_view(
   openapi.Info(
      title="Chatbot API",
      default_version='v1',
      description="API for the Chatbot Application",
      terms_of_service="https://www.google.com/policies/terms/",
      contact=openapi.Contact(email="developer@gmail.com"),
      license=openapi.License(name="BSD License"),
   ),
   public=True,
   permission_classes=(permissions.AllowAny,),
)


# Sentry Debugging(Don't Delete)
def trigger_error(request):
    division_by_zero = 1 / 0

urlpatterns = [
    path('admin/', admin.site.urls),

    # Django Channels Demo App
    path('ws/', include('apps.clientwidget.demo_urls')),

    # DRF API's
    path('api/', include('apps.accounts.urls')),
    path('api/', include('apps.chatbox.urls')),
    path('api/', include('apps.clientwidget.urls')),
    path('api/', include('apps.chatdata.urls')),
]

if config('MODE') == 'DEVELOPMENT':
    urlpatterns += [path('admin/', admin.site.urls)]

urlpatterns  += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
# urlpatterns  += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

