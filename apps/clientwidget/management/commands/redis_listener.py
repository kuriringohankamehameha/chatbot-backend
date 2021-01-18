import re
import signal
import time

import redis
from decouple import UndefinedValueError, config
from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError

from apps.clientwidget import events
from apps.clientwidget.consumers import TemplateChatConsumer
from apps.clientwidget.models import ChatRoom


class Command(BaseCommand):
    help = 'Starts the redis Listener for events regarding session expiry'

    def handle(self, *args, **options):
        self.stdout.write('Started Listener....')

        conn = redis.StrictRedis(host=config("REDIS_SERVER_HOST"), port=config("REDIS_SERVER_PORT"), password=config("REDIS_SERVER_PASSWORD")) # db = 0

        pubsub = conn.pubsub()
        pubsub.psubscribe("*")

        for msg in pubsub.listen():
            # Here, msg = {'pattern': b'*', 'channel': b'__keyspace@1__::1:foo', 'data': b'expire'}
            # Here, we only subscribe to patterns of the form `CLIENTWIDGET*`
            # We're interested in the expiry of keys - Specifically about the `CLIENTWIDGET_EXPIRY_LOCK*` family
            if msg is not None:
                pattern = r'__keyevent@.+\:(.+)'
                event = msg['channel']
                if event is not None:
                    event = event.decode()
                    match = re.match(pattern, event)
                    if match is not None and match.groups()[0] == 'expired':
                        # Key Expiry Event
                        key = msg['data'].decode()
                        pattern = r'\:.+\:(.+)'
                        match = re.match(pattern, key)
                        if match is not None and len(match.groups()) >= 1:
                            key = match.groups()[0]
                            print(key)
                            pattern = r'CLIENTWIDGET_EXPIRY_LOCK_(.+)'
                            match = re.match(pattern, key)
                            if match is not None and len(match.groups()) >= 1:
                                room_name = match.groups()[0]
                                print(f"{room_name} - MATCHING KEY")
                                if True:
                                    TemplateChatConsumer.send_from_api('', room_name, bot_type='website', user='session_timeout')
                                    print(f"Successfully disconnected the sessions for Room - {room_name}")
                                else:
                                    queryset = ChatRoom.objects.filter(room_name=room_name)
                                    for instance in queryset:
                                        # Flush to DB
                                        is_lead = cache.get(f"IS_LEAD_{instance.room_name}")
                                        session_variables = cache.get(f"VARIABLES_{instance.room_name}")
                                        events.flush_to_db(instance.room_id, 'AnonymousUser', session_variables, is_lead=is_lead)
                                        # Make the chat inactive
                                        instance.bot_is_active = False
                                        instance.save()
                                    
                                    # Now finally force delete all the cache keys
                                    cache.delete(f'CLIENTWIDGETROOMLOCK_{room_name}') # Lock for the room
                                    cache.delete(f'CLIENTWIDGETLOCK_{room_name}') # Lock for the room messages                                
                                    cache.delete(f'CLIENTWIDGETLEADFIELDS_{room_name}')
                                    cache.delete(f'CLIENTWIDGETROOMINFO_{room_name}')
                                    cache.delete(f'IS_LEAD_{room_name}')
                                    cache.delete(f"CLIENTWIDGETTIMEOUT_{room_name}")
                                    cache.delete(f"CLIENTWIDGET_EXPIRY_LOCK_{room_name}")
