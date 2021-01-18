from rest_framework import serializers
from django.apps import apps

ChatRoom = apps.get_model(app_label='clientwidget', model_name='ChatRoom')
Chatbox = apps.get_model(app_label='chatbox', model_name='Chatbox')

class ChatHeaderSerializer(serializers.ModelSerializer):
    _required_fields = ("room_id", "room_name", "bot_id", "bot_is_active", "is_lead", "created_on", "updated_on", "end_time", "visitor_id", "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "website_url", "channel_id")
    class Meta:
        model = ChatRoom
    Meta.fields = _required_fields
    Meta.example = list(_required_fields)
    Meta.example.append({'variables': {'@name': "", '@email': ""}})


class BotInfoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Chatbox
        fields = ('bot_hash', 'title',)


class ChatbotListingSerializer(serializers.ModelSerializer):
    bot_info = BotInfoSerializer(read_only=True)
    class Meta:
        model = ChatRoom
        fields = ('bot_info',)

class GsheetTokenSerializer(serializers.Serializer):
    token = serializers.CharField()