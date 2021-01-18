from django.contrib.auth import authenticate
from rest_framework import serializers
import uuid

from apps.clientwidget.models import ChatRoom

from . import models


# Register
class ChatboxListSerializer(serializers.ModelSerializer):
    count_chat = serializers.SerializerMethodField('chat_count')

    def chat_count(self, obj):
        return ChatRoom.objects.using(obj.owner.ext_db_label).filter(bot_id=obj.bot_hash).count()

    class Meta:
        model = models.Chatbox
        fields = ('bot_hash', 'title', 'publish_status', 'count_chat', 'chatbot_type', 'spreadsheetId')


# Register
class ChatboxRegDetailSerializer(serializers.ModelSerializer):
    website_url = serializers.URLField(read_only=True)
    js_file_path = serializers.URLField(read_only=True)
    bot_full_json = serializers.JSONField()
    bot_data_json = serializers.JSONField()
    bot_variable_json = serializers.JSONField()
    bot_lead_json = serializers.JSONField()
    variable_columns = serializers.JSONField()
    subscription_type = serializers.CharField()
    
    class Meta:
        model = models.Chatbox
        fields = ('bot_hash', 'title','website_url', 'js_file_path', 'publish_status', 'bot_full_json', 'bot_data_json', 'bot_variable_json', 'bot_lead_json', 'variable_columns', 'subscription_type', 'chatbot_type')


class ChatRoomSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.ChatRoom
        fields = '__all__'

class ChatBoxMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.ChatboxMessage
        fields = '__all__'

class ClassAppearanceUpdateSerializer(serializers.ModelSerializer):
    chatboxname = serializers.SerializerMethodField()

    class Meta:
        model = models.ChatboxAppearance
        fields = ['chatboxname', 'json_info']

    def get_chatboxname(self, obj):
        return getattr(obj, 'chatboxname', self.context['chatboxname'])

    def update(self, instance, validated_data):
        if self.context['chatboxname'] != '':
            models.Chatbox.objects.filter(pk=int(self.context['chatbox_pk'])).update(title=self.context['chatboxname'])
        return super(ClassAppearanceUpdateSerializer, self).update(instance, validated_data)

class ChatboxMobileAppearanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.ChatboxMobileAppearance
        fields = '__all__'


class ChatboxDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.ChatboxDetail
        fields = '__all__'


class ChatboxPageSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.ChatboxPage
        fields = '__all__'


class ChatboxUrlSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.ChatboxUrls
        fields = ('website_url', 'publish_status', 'js_file_path', 'url_hash', 'allow_subdomain',)


class ChatboxPublishSerializer(serializers.BaseSerializer):
    
    def to_internal_value(self, data):
        bot_hash = data.get('bot_hash')
        website_url = data.get('website_url')
        js_file_path = data.get('js_file_path')
        publish_status = data.get('publish_status')
        url_hash = data.get('url_hash')
        allow_subdomain = data.get('allow_subdomain')

        # Perform the data validation.
        if not bot_hash:
            raise serializers.ValidationError({
                'bot_hash': 'This field is required.'
            })

        if not website_url:
            raise serializers.ValidationError({
                'website_url': 'This field is required.'
            })

        if not js_file_path:
            js_file_path = "" # Default is null
        
        if publish_status not in (True, False): # Beware for Boolean Fields
            raise serializers.ValidationError({
            'publish_status': 'This Boolean Field is required.'
        })

        if not url_hash:
            raise serializers.ValidationError({
            'url_hash': 'This Field is required.'
        })

        if allow_subdomain not in (True, False):
            raise serializers.ValidationError({
            'allow_subdomain': 'This Boolean Field is required.'
        })

        # Return the validated values
        return {
            'bot_hash': bot_hash,
            'website_url': website_url,
            'js_file_path': js_file_path,
            'publish_status': publish_status,
            'url_hash': url_hash,
            'allow_subdomain': allow_subdomain,
        }

    def to_representation(self, instance):
        return {
            #'bot_hash': instance.bot_hash_id,
            'website_url': instance.website_url,
            'js_file_path': instance.js_file_path,
            'publish_status': instance.publish_status,
            'allow_subdomain': instance.allow_subdomain,
            'url_hash': instance.url_hash,
        }

    def create(self, validated_data):
        instance = models.ChatboxUrls.objects.filter(bot_hash=validated_data['bot_hash'], website_url=validated_data['website_url']).first()
        if instance is not None:
            [setattr(instance, field, value) for field, value in validated_data.items()]
            instance.save(update_fields=[field for field in validated_data])
            return instance
        else:
            return models.ChatboxUrls.objects.create(**validated_data)


class SendEmailSerializer(serializers.Serializer):
    from_email = serializers.CharField()
    to_email = serializers.CharField()
    subject = serializers.CharField()
    content = serializers.CharField()


class BotBuilderImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.BotBuilderImage
        fields = ['chatbox', 'image']

class ChatWidgetSerializer(serializers.ModelSerializer):
    variables = serializers.JSONField()
    messages = serializers.JSONField()
    class Meta:
        model = models.ChatWidget
        fields = ('room_id', 'room_name', 'variables', 'messages')


class DuplicateChatbotSerializer(serializers.Serializer):
    bot_hash = serializers.CharField()


# Creating Tempate of chatbot
class CreateChatboxTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.TemplateChatbox
        exclude = ['created_on', 'is_deleted']


class FrontendChatbotTemplateApiSerializer(serializers.Serializer):
    template_bot_hash = serializers.CharField()
