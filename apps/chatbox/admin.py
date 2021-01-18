from django.contrib import admin

# Register your models here.
from .models import Chatbox, ChatboxAppearance, ChatboxMessage, BotBuilderImage, TemplateChatbox

admin.site.register(Chatbox)
admin.site.register(ChatboxAppearance)
admin.site.register(ChatboxMessage)
admin.site.register(BotBuilderImage)
admin.site.register(TemplateChatbox)
