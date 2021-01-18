import sys
import os

from django.core.management.base import BaseCommand
from django.db.models.base import ObjectDoesNotExist

from apps.clientwidget.models import ChatRoom

from decouple import Config, RepositoryEnv, UndefinedValueError

from django.core.cache import cache

DOTENV_FILE = os.path.join(os.getcwd(), 'chatbot', '.env')
env_config = Config(RepositoryEnv(DOTENV_FILE))

from django.conf import settings
from django.db import transaction

import uuid
import json

try:
    USE_CELERY = env_config.get('USE_CELERY')
except UndefinedValueError:
    USE_CELERY = False

CHUNK_SIZE = 5000

def clear_ns(conn, ns):
    cursor = '0'
    ns_keys = ns + '*'
    while cursor != 0:
        cursor, keys = conn.scan(cursor=cursor, match=ns_keys, count=CHUNK_SIZE)
        if keys:
            conn.delete(*keys)

    return True

def redis_server_reset_rooms():
    connection = cache.get_client('')
    clear_ns(connection, cache.make_key("NUM_USERS_"))


class Command(BaseCommand):
    help = 'Resets the number of members of all existing rooms to 0'

    def handle(self, *args, **options):
        redis_server_reset_rooms()
        print('Reset all rooms!')
