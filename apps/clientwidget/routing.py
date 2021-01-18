# Global routing configuration
from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter

# Application Routing Configuration starts here
# TODO: Wrap this up inside a separate application
from django.urls import re_path

from . import consumers


import os
import time
from django.shortcuts import render, HttpResponse, reverse
from channels.auth import AuthMiddlewareStack
from channels.sessions import SessionMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from django.urls import re_path, path
import json
from channels.generic.websocket import WebsocketConsumer


websocket_urlpatterns = [
    path('ws/chat_updated/<uuid:owner_id>/<uuid:operator_id>/operator', consumers.OperatorConsumer),
    path('ws/chat_updated/<uuid:owner_id>/<uuid:room_id>', consumers.ClientWidgetConsumer),
    path('ws/chat_updated/<uuid:owner_id>/admin', consumers.AdminConsumer),
    path('ws/chat_updated/<uuid:owner_id>/listing', consumers.LongPollingConsumer),
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

