from django.urls import path, include
from . import api
from . import views

from .routing import channels_testing
from django.views.decorators.csrf import csrf_exempt

# TODO: Make the URL prefixes as 'chatbox/' instead of '/' in the parent application
urlpatterns = [
    path('chatbox', api.ChatboxList.as_view()),
    # According to payment display
    path('chatboxes', api.ChatboxListAPI.as_view()),
    path('chatbox/<uuid:pk>', api.ChatboxDetailAPI.as_view()),
    path('chatbox/', views.index, name='index'),
    path('chatbox/<str:room_name>/', views.room, name='room'),
    path('chatbox/livechat/<str:room_name>/', views.adminroom, ),

    path('chatbox/<uuid:pk>/chatboxappeareance', api.ChatboxAppearanceUpdateView.as_view(), name='update_app'),
    path('chatbox/<uuid:pk>/chatboxmobileappeareance', api.ChatboxMobileAppearanceUpdateView.as_view(),
         name='update_app'),
     path('chatbox/<uuid:pk>/customization', api.ChatboxCustomizationView.as_view(), name='chatbox customization'),

    path('chatbox/<uuid:pk>/chatboxdetail', api.ChatboxDetailUpdateView.as_view(),
         name='update_detail'),
    path('chatbox/<uuid:pk>/chatboxpage', api.ChatboxPageUpdateView.as_view(),
         name='update_page'),
     path('channels_test/', channels_testing, name='channels_testing'),
     path('chatbox/<uuid:pk>/publish', api.PublishChatbox.as_view()),
     path('chatbox/<uuid:pk>/publish/<str:url_hash>', api.PublishChatbox.as_view()),
     path('chatbox/send_mail', api.SendEmail.as_view()),
     path('chatbox/upload/image/<uuid:pk>', api.BotBuilderImageAPI.as_view(), name='catbox_image'), 
     path('chatbox/duplicate', api.DuplicateChatbot.as_view()),
     path('chatbox/delete/<uuid:pk>', api.DeleteChatbot.as_view()),
     path('chatbox/template', api.CreateChatboxTemplate.as_view()),
     path('chatbox/template/update/<uuid:pk>', api.UpdateChatboxTemplate.as_view()),
     path('chatbox/template/frontend', api.FrontendChatbotTemplateApi.as_view()),
     path('chatbox/client_media/<uuid:room_id>', csrf_exempt(api.ClientMediaHandlerAPI.as_view())),
     path('chatbox/admin_media/<uuid:room_id>', api.AdminMediaHandlerAPI.as_view()),
     path('chatbox/metric/<uuid:bot_id>', api.BotLevelMetric.as_view()),
     path('chatbox/isallowed', api.botjs_handler),
     path('chatbox/<uuid:pk>/urls', api.ChatboxUrlListAPI.as_view()),
]
