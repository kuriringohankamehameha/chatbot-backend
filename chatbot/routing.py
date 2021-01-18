# Global routing configuration
from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
import apps.clientwidget.routing, apps.chatbox.routing

application = ProtocolTypeRouter({
    # If a connection is a websocket connection,
    # the ProtocolTypeRouter will give this to our Middleware    
    'websocket': AuthMiddlewareStack(
        # AuthMiddlewareStack populates the connection's scope with a reference
        # to the currently authenticated user  
        URLRouter(
            # Finally, URLRouter examines the HTTP path
            # and route to a consumer, if any, using the chat application's urlpatterns
            apps.clientwidget.routing.websocket_urlpatterns
            +
            apps.chatbox.routing.websocket_urlpatterns
        )
    ),
})
