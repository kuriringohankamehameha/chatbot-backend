from django.urls import path
from . import api
from . import views
from django.views.decorators.csrf import csrf_exempt


urlpatterns = [
    # url
    # path('webhook', csrf_exempt(views.WhatsappView.as_view())),

    ## api for test channels
    path('scheduler', api.WhatsappMakeSchedule.as_view()),
    path('scheduler/<uuid:pk>', api.WhatsappMakeScheduleDetailAPI.as_view()),

    path('superadmin/getallscheduler/<int:admin>', api.WhatsappMakeSchedule.as_view()),
    path('superadmin/getallscheduler/<uuid:pk>', api.WhatsappMakeScheduleDetailAPI.as_view()),

    path('sendhsm/<uuid:pk>/<int:now>', api.WhatsappSendTemplateMessage.as_view()),     ## send template messages
    path('runningscheduler/<uuid:pk>/<int:delete>/<int:admin>', api.RunningSchedulerDetails.as_view()),
]
