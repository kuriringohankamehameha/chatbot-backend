from decouple import config
from django.urls import path

try:
     DEVELOPMENT = config('DEVELOPMENT', cast=bool)
except:
     DEVELOPMENT = False

from . import api
from . import views
from .testingModule import api as testing_api

PREFIX = 'clientwidget'

if DEVELOPMENT == True:
     demo_patterns = [
          path(f'{PREFIX}/demo', views.index, name='client widget demo index'),
          path(f'{PREFIX}/demo/<uuid:owner_id>/<uuid:room_id>', views.room, name='client widget demo room'),
          path(f'{PREFIX}/demo/iptest', api.IPTest.as_view(), name='client widget demo ip test'),
          path(f'{PREFIX}/demo/test', api.TestingAPI.as_view(), name='client widget demo test api'),
          path(f'{PREFIX}/testing/webhook', testing_api.TestingWebhookCompoenent.as_view())
     ]
else:
     demo_patterns = []

urlpatterns = demo_patterns + [     
     path(f'{PREFIX}/session/<uuid:bot_id>', api.TemplateChatbot.as_view(), name='client widget bot session'),
     path(f'{PREFIX}/session/preview/<uuid:bot_id>', api.TemplatePreviewChatbot.as_view(), name='client widget preview bot session'),
     
     path(f'{PREFIX}/listing', api.ActiveChatBotListing.as_view(),
          name='client widget active bots'),
     path(f'{PREFIX}/listing/sort/<str:sort_date>', api.ActiveChatBotListing.as_view(),
          name='client widget active bots sort'),
     path(f'{PREFIX}/listing/type/<str:bot_type>', api.ActiveChatBotListing.as_view(),
          name='client widget active bot type'),
     path(f'{PREFIX}/listing/type/<str:bot_type>/sort/<str:sort_date>', api.ActiveChatBotListing.as_view(),
          name='client widget active bot type sort'),
     
     path(f'{PREFIX}/listing/inactive', api.InactiveChatBotListing.as_view(),
          name='client widget inactive bots'),
     path(f'{PREFIX}/listing/inactive/sort/<str:sort_date>', api.InactiveChatBotListing.as_view(),
          name='client widget inactive bots sort'),
     path(f'{PREFIX}/listing/inactive/type/<str:bot_type>', api.InactiveChatBotListing.as_view(),
          name='client widget inactive bot type'),
     path(f'{PREFIX}/listing/inactive/type/<str:bot_type>/sort/<str:sort_date>', api.InactiveChatBotListing.as_view(),
          name='client widget inactive bot type sort'),
     
     path(f'{PREFIX}/deactivate/<uuid:room_id>', api.DeactivateChatbot.as_view(),
          name='client widget deactivate bot'),
     
     path(f'{PREFIX}/session/<uuid:room_id>/emit', api.SendMessageToWebsocket.as_view(),
          name='client widget send to websocket'),
     
     
     path(f'{PREFIX}/<uuid:room_id>/history', api.ChatHistoryDB.as_view()),
     path(f'{PREFIX}/<uuid:room_id>/history/<int:num_msgs>', api.ChatHistoryDB.as_view()),
     
     path(f'{PREFIX}/<uuid:room_id>/sessionhistory', api.ChatHistoryRedis.as_view()),
     path(f'{PREFIX}/<uuid:room_id>/sessionhistory/<int:num_msgs>', api.ChatHistoryRedis.as_view()),
     
     path(f'{PREFIX}/<uuid:room_id>/variables', api.FetchVariablesDB.as_view()),
     path(f'{PREFIX}/<uuid:room_id>/sessionvariables', api.FetchVariablesRedis.as_view()),
     
     path(f'{PREFIX}/<uuid:room_id>/flush', api.FlushSessiontoDB.as_view()),
     path(f'{PREFIX}/<uuid:room_id>/flush/<int:reset>', api.FlushSessiontoDB.as_view()),
     path(f'{PREFIX}/utm_code/<uuid:room_id>', api.UTMCodeAPI.as_view()),
     path(f'{PREFIX}/force_inactive/<uuid:owner_id>/<uuid:room_id>', api.MakeChatRoomsInactive.as_view()),
     
]
