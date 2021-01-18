from urllib import parse
from urllib.parse import parse_qs, unquote, urlparse

from channels.auth import AuthMiddlewareStack
from django.conf import LazySettings
from django.contrib.auth.models import AnonymousUser
from django.db import close_old_connections


class ClientWidgetMiddleware:

    def __init__(self, inner):
        self.inner = inner

    def __call__(self, scope):
        close_old_connections()
        query_string = parse_qs(scope['query_string']) #Used for query string token url auth
        return self.inner(scope)


ClientWidgetMiddlewareStack = lambda inner: ClientWidgetMiddleware(AuthMiddlewareStack(inner))
