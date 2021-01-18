# Global routing configuration
from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter

# Application Routing Configuration starts here
# TODO: Wrap this up inside a separate application
from django.urls import re_path

import os
import time
from django.shortcuts import render, HttpResponse, reverse
from channels.auth import AuthMiddlewareStack
from channels.sessions import SessionMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from django.urls import re_path
import json
from channels.generic.websocket import WebsocketConsumer
class ChatConsumer1(WebsocketConsumer):
    count = 0

    def connect(self):
        self.accept()
        self.send(text_data=json.dumps({
            'message': 'testing:connected',
        }))

    def disconnect(self, close_code):
        pass

    def receive(self, text_data=None, bytes_data=None):
        text_data_json = json.loads(text_data)
        message = text_data_json['message']
        if ChatConsumer1.count != 20:
            time.sleep(3)
            print(message, ChatConsumer1.count)
            self.send(text_data=json.dumps({
                'message': 'testing:{}'.format(ChatConsumer1.count),
            }))
            ChatConsumer1.count += 1


basedir = os.path.dirname(os.path.realpath(__file__))
def channels_testing(request):
    return HttpResponse(open(os.path.join(basedir, 'templates/channels_testing.html')))

websocket_urlpatterns = [
    re_path(r'ws/chatbox/testing/api/(?P<room_name>\w+)/$', ChatConsumer1),
]

application = ProtocolTypeRouter({
    # If a connection is a websocket connection,
    # the ProtocolTypeRouter will give this to our Middleware
    # AuthMiddlewareStack populates the connection's scope with a reference
    # to the currently authenticated user   
    'websocket': AuthMiddlewareStack(
        # SessionMiddlewareStack for using Sessions
        SessionMiddlewareStack(
            URLRouter(
                # Finally, URLRouter examines the HTTP path
                # and route to a consumer, if any, using the chat application's urlpatterns
                websocket_urlpatterns
            )
        )
    )
})
