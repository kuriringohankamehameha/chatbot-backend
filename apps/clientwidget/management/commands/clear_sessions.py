import json
import os
import sys
import uuid

from decouple import Config, RepositoryEnv, UndefinedValueError
from django.conf import settings
from django.contrib.sessions.models import Session
from django.core.cache import cache
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.clientwidget.models import ChatRoom

DOTENV_FILE = os.path.join(os.getcwd(), 'chatbot', '.env')
env_config = Config(RepositoryEnv(DOTENV_FILE))



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

def fetch_batch(conn, ns):
    cursor = '0'
    ns_keys = ns + '*'
    while cursor != 0:
        cursor, keys = conn.scan(cursor=cursor, match=ns_keys, count=CHUNK_SIZE)
        if keys:
            yield keys
            conn.delete(*keys)
    return True

def redis_server_cleanup():
    connection = cache.get_client('')
    generator = fetch_batch(connection, cache.make_key("CLIENTWIDGETLOCK_"))
    while True:
        # Clear up any existing sessions
        try:
            batch = next(generator)
            # Dump to DB
            for key in batch:
                room_name = json.loads(connection.get(key))
                variables = cache.get("VARIABLES_" + room_name)
                messages_bytes = connection.lrange(cache.make_key("HISTORY_" + room_name), 0, -1)
                messages = list(json.loads(message) for message in messages_bytes)[::-1]
                modified = False
                with transaction.atomic():
                    instance = ChatRoom.objects.get(room_name=room_name)
                    if variables is not None:
                        instance.variables = variables
                        modified = True
                    if messages is not None:
                        if messages != []:
                            instance.messages.extend(messages)
                            modified = True
                    if modified:
                        instance.save()
        except StopIteration:
            break
    clear_ns(connection, cache.make_key("BOT_PREVIEW_VARIABLE_"))
    clear_ns(connection, cache.make_key("NUM_USERS_"))
    clear_ns(connection, cache.make_key("HISTORY_"))

    # Clear all sessions
    stored_sessions = Session.objects.all()
    for session in stored_sessions:
        SessionStore = import_module(settings.SESSION_ENGINE).SessionStore
        sess = SessionStore(session_key=session.session_key)
        session_uid = session.get_decoded().get('_auth_user_id')
        sess.delete()


class Command(BaseCommand):
    help = 'Cleanup Existing Chat Sessions from Redis and Dump them into DB'

    def handle(self, *args, **options):
        redis_server_cleanup()
        print('Finished cleaning up existing sessions!')
