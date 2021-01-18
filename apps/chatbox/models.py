from django.db import models
from django.conf import settings
import uuid
from django.utils.translation import ugettext_lazy as _
import jsonfield
from django.db.models.signals import post_save
from django.dispatch import receiver

# TODO: Remove This
class ChatRoom(models.Model):
    uuid = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_on = models.DateTimeField(_('chatroom created on'), auto_now_add=True)
    room_name = models.CharField(max_length=1000, null=True)
    current_state = models.CharField(max_length=100, null=True, db_column='current_state')
    bot_id = models.UUIDField(db_column='bot_id')
    bot_is_active = models.BooleanField(default=False, db_column='bot_is_active')
    num_msgs = models.PositiveIntegerField(default=0, db_column='num_msgs') 

# TODO: Remove This
class ChatboxMessage(models.Model):
    # TODO: Maintain a reference to the User model and get user information
    chat_room = models.CharField(max_length=1000)
    room_id = models.ForeignKey('ChatRoom', on_delete=models.CASCADE, db_column='room_id')
    user_name = models.CharField(max_length=1000)
    msg_num = models.IntegerField(primary_key=True)
    message = models.CharField(max_length=1000)
    time = models.CharField(max_length=30, null=True, blank=True, db_column='time')

class ChatboxUrls(models.Model):
    # Model which maps a single website bot to multiple hosted URLs
    bot_hash = models.ForeignKey('Chatbox', related_name="chatbox_urls", db_column="bot_hash", on_delete=models.CASCADE)
    website_url = models.URLField(max_length=255, blank=True, db_column="website_url")
    url_hash = models.CharField(max_length=255, null=True, blank=True)
    js_file_path = models.URLField(max_length=255, blank=True, db_column="js_file_path", default="")
    publish_status = models.BooleanField(default=False, db_column="publish_status")
    allow_subdomain = models.BooleanField(default=False)


class Chatbox(models.Model):
    bot_hash = models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True)
    title = models.CharField(max_length=100)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="chatbox", on_delete=models.CASCADE)
    created_on = models.DateTimeField(auto_now_add=True)
    publish_status =  models.BooleanField(default=False)
    preview_url = models.URLField(max_length = 200, null=True, blank=True)
    spreadsheetId = models.CharField(max_length=255, blank=True, null=True)
    website_url = models.URLField(max_length=255, blank=True)
    js_file_path = models.URLField(max_length=255, blank=True, default="")  
    bot_full_json = jsonfield.JSONField(null=True, blank=True)
    bot_data_json = jsonfield.JSONField(null=True, blank=True)
    bot_variable_json = jsonfield.JSONField(null=True, blank=True)
    bot_lead_json = jsonfield.JSONField(null=True, blank=True)
    CHATBOT_TYPE = (
	('website', 'WEBSITE'),
	('whatsapp', 'WHATSAPP'),
    ('facebook', 'FACEBOOK'),
    ('apichat', 'APICHAT'),
    )
    chatbot_type = models.CharField(max_length=10, choices=CHATBOT_TYPE, default='website')
    active = models.BooleanField(default=True)
    is_deleted = models.BooleanField(default=False)
    variable_columns = jsonfield.JSONField(null=True, blank=True)
    SUBSCRIPTION_TYPE = (
        ('', 'NONE'),
        ('email', 'EMAIL'),
        ('cron', 'CRON'),
        ('all', 'ALL'),
    )
    subscription_type = models.CharField(max_length=10, choices=SUBSCRIPTION_TYPE, default='', null=True)
    customizations = jsonfield.JSONField(null=True, blank=True, default=dict)
    canvas_version = models.CharField(max_length=10, default='v1')

    def publish(self, website_url, js_file_path):
        self.website_url = str(website_url)
        self.js_file_path = js_file_path
        self.publish_status = True
        self.save()
        
    
# TODO: Remove This
class ChatboxAppearance(models.Model):
    chatbox = models.OneToOneField(Chatbox, related_name="chatbox_appearance", on_delete=models.CASCADE)
    theme = models.CharField(max_length=30, default='defaultTheme', null=True, blank=True) 
    custom_theme = jsonfield.JSONField(null=True, blank=True)
    online_status = models.CharField(max_length=100, default='Online', null=True, blank=True) 
    offline_status = models.CharField(max_length=100, default='Offline', null=True, blank=True) 
    offline_msg = models.CharField(max_length=250, default="We’re currently unavailable.", null=True, blank=True)     
    WIDGET_POS = (
        ('L', 'Left'),
        ('R', 'Right'),
    )
    widget_position = models.CharField(max_length=1, choices=WIDGET_POS, default='R')
    CHAT_VISIBILITY = (
        ('1', 'Both on Mobile and Desktop Devices'),
        ('2', 'Only on Mobile Devices'),
        ('3', 'Only on Desktop Devices'),
        ('4', 'Hide Widget'),
        ('5', 'Advanced Rules'),
    )
    visibility = models.CharField(max_length=1, choices=CHAT_VISIBILITY, default='1')
    button_label = models.BooleanField(default=False)
    label_text = models.CharField(max_length=100, default='Chat with us ') 
    widget_sound = models.BooleanField(default=True)
    defaultOpen = models.BooleanField(default=False)
    current_status = models.BooleanField(default=False)
    json_info = jsonfield.JSONField(null=True, blank=True, default=dict)

    @receiver(post_save, sender=Chatbox)
    def create_chatbox_appearance(sender, instance, created, **kwargs):
        if created:
            ChatboxAppearance.objects.create(chatbox=instance)

    @receiver(post_save, sender=Chatbox)
    def save_chatbox_appearance(sender, instance, **kwargs):
        instance.chatbox_appearance.save()

class ChatboxMobileAppearance(models.Model):
    chatbox = models.OneToOneField(Chatbox, related_name="chatbox_mobile_appearance", on_delete=models.CASCADE)
    WIDGET_POS = (
        ('L', 'Left'),
        ('R', 'Right'),
    )
    widget_position = models.CharField(max_length=1, choices=WIDGET_POS, default='R')
    WIDGET_SIZE = (
        ('S', 'Small'),
        ('M', 'Medium'),
        ('L', 'Large'),
    )
    widget_size = models.CharField(max_length=1, choices=WIDGET_SIZE, default='L')
    json_info = jsonfield.JSONField(null=True, blank=True, default=dict)

    @receiver(post_save, sender=Chatbox)
    def create_chatbox_mobile_appearance(sender, instance, created, **kwargs):
        if created:
            ChatboxMobileAppearance.objects.create(chatbox=instance)

    @receiver(post_save, sender=Chatbox)
    def save_chatbox_mobile_appearance(sender, instance, **kwargs):
        instance.chatbox_mobile_appearance.save()
    
# TODO: Remove This
class ChatboxDetail(models.Model):
    chatbox = models.OneToOneField(Chatbox, related_name="chatbox_detail", on_delete=models.CASCADE)
    status = models.CharField(max_length=100, default='Hi there ') 
    message = models.CharField(max_length=250, default='Welcome to our website. Ask us anything ', null=True, blank=True) 

    @receiver(post_save, sender=Chatbox)
    def create_chatbox_detail(sender, instance, created, **kwargs):
        if created:
            ChatboxDetail.objects.create(chatbox=instance)

    @receiver(post_save, sender=Chatbox)
    def save_chatbox_detail(sender, instance, **kwargs):
        instance.chatbox_detail.save()

# TODO: Remove This
class ChatboxPage(models.Model):
    chatbox = models.OneToOneField(Chatbox, related_name="chatbox_page_detail", on_delete=models.CASCADE)
    page_title = models.CharField(max_length=100, null=True, blank=True) 
    color = models.CharField(max_length=7, default='#2A27DA') 
    message = models.CharField(max_length=250, default='Welcome to our website. Ask us anything ', null=True, blank=True) 
    company_logo = models.ImageField(upload_to='chatbox/company/page-logo/', null=True, blank=True)
    company_url = models.URLField(max_length = 200, null=True, blank=True) 
    header_msg = models.CharField(max_length=100, default='Welcome') 
    welcome_msg = models.CharField(max_length=250, default='Ask us anything ', null=True, blank=True) 
    chatpage_url = models.URLField(max_length = 300, null=True, blank=True) 
    seo_title = models.CharField(max_length=250, null=True, blank=True) 
    seo_description = models.CharField(max_length=250, null=True, blank=True) 

    @receiver(post_save, sender=Chatbox)
    def create_chatbox_page_detail(sender, instance, created, **kwargs):
        if created:
            ChatboxPage.objects.create(chatbox=instance)

    @receiver(post_save, sender=Chatbox)
    def save_chatbox_page_detail(sender, instance, **kwargs):
        instance.chatbox_page_detail.save()


# BOTBUILDER IMAGE
class BotBuilderImage(models.Model):
    chatbox = models.ForeignKey(Chatbox, on_delete=models.CASCADE, related_name='image_chatbox')
    image = models.FileField(upload_to='bot_images/', max_length=100)
    created = models.DateTimeField(auto_now_add=True)
    active = models.BooleanField(default=True)

# Chatbox Widget
from django.contrib.postgres.fields import JSONField

# TODO: Remove This
class ChatWidget(models.Model):
    room_id = models.ForeignKey('ChatRoom', related_name='chatroom', db_column='room_id', on_delete=models.CASCADE)
    room_name = models.CharField(max_length=1000, null=True)
    messages = JSONField(db_column='messages', default=list)
    variables = JSONField(db_column='variables', default=list)


class TemplateChatbox(models.Model):
    bot_hash = models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True)
    title = models.CharField(max_length=100)
    image = models.ImageField(upload_to='chatbot_template/', null=True)
    created_on = models.DateTimeField(auto_now_add=True)
    bot_full_json = jsonfield.JSONField(null=True, blank=True)
    bot_data_json = jsonfield.JSONField(null=True, blank=True)
    bot_variable_json = jsonfield.JSONField(null=True, blank=True)
    bot_lead_json = jsonfield.JSONField(null=True, blank=True)
    CHATBOT_TYPE = (
	('website', 'WEBSITE'),
	('whatsapp', 'WHATSAPP'),
    ('facebook', 'FACEBOOK'),
    ('apichat', 'APICHAT'),
    )
    chatbot_type = models.CharField(max_length=10, choices=CHATBOT_TYPE, default='website')
    is_deleted = models.BooleanField(default=False)
    variable_columns = jsonfield.JSONField(null=True, blank=True)
    SUBSCRIPTION_TYPE = (
        ('', 'NONE'),
        ('email', 'EMAIL'),
    )
    subscription_type = models.CharField(max_length=10, choices=SUBSCRIPTION_TYPE, default='', null=True, blank=True)
    customizations = jsonfield.JSONField(null=True, blank=True, default=dict)

