from django.contrib.auth import authenticate
from rest_framework import serializers

from apps.chatbox.models import Chatbox

from apps.clientwidget import models
import datetime, time



class ChatRoomSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.ChatRoom
        fields = '__all__'


class BotInfoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Chatbox
        fields = ('bot_hash', 'title', 'chatbot_type')


class ActiveChatRoomSerializer(serializers.ModelSerializer):
    bot_info = BotInfoSerializer(read_only=True)
    class Meta:
        model = models.ChatRoom
        fields = ('bot_id', 'room_id', 'room_name', 'created_on', 'bot_is_active', 'variables', 'bot_info', 'status', 'chatbot_type', 'assignment_type', 'assigned_operator', 'channel_id', 'updated_on')

class ChatWidgetSerializer(serializers.ModelSerializer):
    variables = serializers.JSONField()
    messages = serializers.JSONField()
    class Meta:
        model = models.ChatRoom
        fields = ('bot_id', 'room_id', 'room_name', 'variables', 'messages')


class VariableSerializer(serializers.ModelSerializer):
    variables = serializers.JSONField()
    class Meta:
        model = models.ChatRoom
        fields = ('variables',)


class VariableDataSerializer(serializers.ModelSerializer):
    variables = serializers.JSONField()
    class Meta:
        model = models.ChatRoom
        fields = ('bot_id', 'room_id', 'room_name', 'variables', 'bot_is_active', "is_lead", "created_on", "updated_on", "end_time", "visitor_id", "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "website_url", "channel_id",)

    def to_representation(self, instance):
        offset = self.context.get('utc_offset')
        if not offset:
            offset = +330
        
        representation = {}
        for field in self.Meta.fields:
            if field not in ('created_on', 'end_time', 'updated_on'):
                if hasattr(instance, field):
                    representation[field] = getattr(instance, field)
            else:
                if getattr(instance, field) is None:
                    representation[field] = None
                else:
                    representation[field] = timezone.template_localtime(getattr(instance, field)) + datetime.timedelta(minutes=offset)
                    try:
                        fmt = "%d:%m:%Y %H:%M:%S"
                        datetime_string = representation[field].strftime(fmt)
                        representation[field] = datetime_string
                    except:
                        pass
        return representation


class ChatOperatorAssignmentSerializer(serializers.Serializer):
    operator_id = serializers.EmailField()
    room_name = serializers.CharField()


class ChatRoomSessionSerializer(serializers.ModelSerializer):
    session_time = serializers.SerializerMethodField('get_session_time')

    def get_session_time(self, obj):

        now = datetime.datetime.now(datetime.timezone.utc)
        n = (now - obj.created_on)
        return time.strftime("%H:%M:%S", time.gmtime(n.total_seconds()))

    class Meta:
        model = models.ChatRoom
        fields = ['created_on', 'session_time']


class UTMCodeSerializer(serializers.ModelSerializer):
    bot_id = serializers.UUIDField()
    class Meta:
        model = models.ChatRoom
        fields = ['utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content', 'bot_id', 'website_url']


class UTMCodeSerializerGetter(serializers.ModelSerializer):
    class Meta:
        model = models.ChatRoom
        fields = ['utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content']

class ChatRoomDetailSerializer(serializers.ModelSerializer):

    bot_type = serializers.SerializerMethodField('get_bot_type')
    owner = serializers.SerializerMethodField('get_owner')
    is_deleted = serializers.SerializerMethodField('check_is_bot_deleted')
    bot_is_active = serializers.SerializerMethodField('make_room_inactive')


    class Meta:
        model = models.ChatRoom
        fields = ('bot_id', 'room_id', 'room_name', 'created_on', 'updated_on', 'variables', 'status', 'takeover', 'assignment_type', 'assigned_operator',
        'bot_type', 'owner', 'is_deleted', 'bot_is_active')

    def get_bot_type(self, obj):
        return obj.chatbot_type

    def get_owner(self, obj):
        return self.context['owner_uuid']

    def check_is_bot_deleted(self, obj):
        chatbox = Chatbox.objects.get(pk=obj.bot_id)
        return chatbox.is_deleted

    def make_room_inactive(self, obj):
        return False

