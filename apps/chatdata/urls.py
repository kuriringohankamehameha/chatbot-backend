from django.urls import path

from . import api
from . import views

urlpatterns = [
    path('chatdata/listing', api.ChatbotListAPI.as_view()),
    path('chatdata/headers/<uuid:bot_id>', api.ChatDataHeaderAPI.as_view()),
    path('chatdata/all/<str:chat_type>', api.ChatDataGlobalAPI.as_view()),
    path('chatdata/bot/<uuid:bot_id>', api.ChatDataBotAPI.as_view()),
    path('chatdata/room/<str:room_name>', api.ChatDataRoomAPI.as_view()),
    path('chatdata/gsheets/<uuid:bot_id>', api.ExportToGsheets.as_view()),    
    path('chatdata/bot/<uuid:bot_id>/count/leads', api.ChatDataCountLeads.as_view()),
    path('chatdata/bot/<uuid:bot_id>/count/leads/<str:start_date>', api.ChatDataCountLeads.as_view()),
    path('chatdata/bot/<uuid:bot_id>/count/leads/<str:start_date>/<str:end_date>', api.ChatDataCountLeads.as_view()),
    path('chatdata/bot/<uuid:bot_id>/count/visitors', api.ChatDataCountVisitors.as_view()),
    path('chatdata/bot/<uuid:bot_id>/count/visitors/<str:start_date>', api.ChatDataCountVisitors.as_view()),
    path('chatdata/bot/<uuid:bot_id>/count/visitors/<str:start_date>/<str:end_date>', api.ChatDataCountVisitors.as_view()),
    
    path('chatdata/bot/<uuid:bot_id>/filter/is_lead/<str:is_lead>', api.ChatDataSortAPI.as_view()),
    path('chatdata/bot/<uuid:bot_id>/filter/date/<str:start_date>', api.ChatDataSortAPI.as_view()),
    path('chatdata/bot/<uuid:bot_id>/filter/date/<str:start_date>/<str:end_date>', api.ChatDataSortAPI.as_view()),
    path('chatdata/bot/<uuid:bot_id>/sort/<str:field>', api.ChatDataSortAPI.as_view()),
    path('chatdata/bot/<uuid:bot_id>/sort/<str:field>/order/<str:order>', api.ChatDataSortAPI.as_view()),
    path('chatdata/bot/<uuid:bot_id>/sort/<str:field>/order/<str:order>/filter/is_lead/<str:is_lead>', api.ChatDataSortAPI.as_view()),
    path('chatdata/bot/<uuid:bot_id>/sort/<str:field>/order/<str:order>/filter/date/<str:start_date>', api.ChatDataSortAPI.as_view()),
    path('chatdata/bot/<uuid:bot_id>/sort/<str:field>/order/<str:order>/filter/date/<str:start_date>/<str:end_date>', api.ChatDataSortAPI.as_view()),

    path('chatdata/export/all/<str:chat_type>', api.ExportBotChatDataAPI.as_view()),
    path('chatdata/export/all/<str:chat_type>/<str:fmt>', api.ExportBotChatDataAPI.as_view()),

    path('chatdata/export/bot/<uuid:bot_id>', api.ExportBotChatDataAPI.as_view()),
    path('chatdata/export/bot/<uuid:bot_id>/<str:fmt>', api.ExportBotChatDataAPI.as_view()),

    path('chatdata/email/all', api.SendChatDataEmailAPI.as_view()),
    path('chatdata/email/all/<str:fmt>', api.SendChatDataEmailAPI.as_view()),
    path('chatdata/email/bot/<uuid:bot_id>', api.SendChatDataEmailAPI.as_view()),
    path('chatdata/email/bot/<uuid:bot_id>/<str:fmt>', api.SendChatDataEmailAPI.as_view()),

    path('chatdata/update/is_leads', api.UpdateLeadsAPI.as_view()),
]