import json
import os
import uuid
from datetime import datetime

from asgiref.sync import async_to_sync, sync_to_async
from celery import Celery, shared_task, task
from channels.layers import get_channel_layer
from decouple import RepositoryEnv, UndefinedValueError, config
from django.apps import apps
from django.conf import settings
from django.core.cache import cache
from django.core.mail import EmailMessage, get_connection, send_mail
from django.db import transaction
from django.template.loader import render_to_string
from django.utils.encoding import force_bytes, force_text
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.utils import timezone
from chatbot.settings import CELERY_BROKER_URL, CELERY_RESULT_BACKEND

from .exceptions import LiveChatException, log_consumer_exceptions, logger

# Create a celery object
# Call it using eventlet for parallelism in Windows: `celery worker -A apps.chatbox.tasks --pool=eventlet --loglevel=info`
# Refer this Github issue for more details (https://github.com/celery/celery/issues/4178)
celery = Celery('tasks', broker=CELERY_BROKER_URL, backend=CELERY_RESULT_BACKEND)

# Refer https://stackabuse.com/asynchronous-tasks-in-django-with-redis-and-celery/
# http://www.marinamele.com/2014/02/how-to-install-celery-on-django-and.html

# Do dis shit instead of stupidly calling apps.chatbox.tasks:
# celery worker -A chatbot --pool=eventlet --loglevel=info

channel_layer = get_channel_layer()


def fetch_history_from_redis(room_id, num_msgs=None, post_delete=False):
    """
        Fetches the most recent num_msgs from Redis on a particular room
    """
    try:
        
        room_name = room_id
        
        REDIS_CONNECTION = cache.get_client('')
        if num_msgs is None:
            history_bytes = REDIS_CONNECTION.lrange(cache.make_key(f'HISTORY_{room_name}'), 0, -1)
        else:
            if num_msgs <= 0:
                return []
            else:
                history_bytes = REDIS_CONNECTION.lrange(cache.make_key(f'HISTORY_{room_name}'), 0, num_msgs-1)
        history = list(json.loads(msg) for msg in history_bytes) # history is now a Python List of Dict
        if post_delete:
            REDIS_CONNECTION.delete(cache.make_key(f"HISTORY_{room_name}"))
        print("in clientwidget_updated fetch_history_from_redis: ", room_name, history)
        return history
    except Exception as ex:
        print(ex)
        return []



def append_msg_to_redis(room_name, message_dict, store_full=False, timeout=None):
    """
        Appends the message dictionary from the websocket to the Redis Message List
    """
    try:
        room_name = uuid.UUID(room_name)
        REDIS_CONNECTION = cache.get_client('')

        if store_full:
            REDIS_CONNECTION.rpush(cache.make_key(f'HISTORY_{room_name}'), json.dumps(message_dict))
            # Finally set a lock on this room name. We'll need it later for flushing to DB
            cache.set(f'CLIENTWIDGETLOCK_{room_name}', room_name, timeout=timeout)
            return

        if 'message' in message_dict:
            if isinstance(message_dict['message'], list):
                # If we want to store an array of parsed messages
                for msg in message_dict['message']:
                    REDIS_CONNECTION.rpush(cache.make_key(f'HISTORY_{room_name}'), json.dumps(msg))
            else:
                REDIS_CONNECTION.rpush(cache.make_key(f'HISTORY_{room_name}'), json.dumps(message_dict))
        else:
            REDIS_CONNECTION.rpush(cache.make_key(f'HISTORY_{room_name}'), json.dumps(message_dict))
        
        # Finally set a lock on this room name. We'll need it later for flushing to DB
        cache.set(f'CLIENTWIDGETLOCK_{room_name}', room_name, timeout=timeout)
    except Exception as ex:
        print(ex)


@task
def flush_db_task(room_id: uuid.UUID, user: str, variables: dict, is_lead=None, db_label='default', bot_type="website") -> None:
    """Flushes the entire session content to the DB

    Args:
        room_id (uuid.UUID): The room id
        user (str): The user email (Will default to 'AnonymousUser' for non authenticated Users)
        variables (dict): A dictionary consisting of all variables for the current session
    """

    print("in flush_db_task:", room_id)
    ChatRoom = apps.get_model(app_label='clientwidget', model_name='ChatRoom')
    
    # Dump messages and session variables
    with transaction.atomic():
        instance = ChatRoom.objects.using(db_label).get(pk=room_id)
        if variables is not None:
            instance.variables = variables
        else:
            print(f"Is there a bug with the flow? Variables is NULL for Room: {room_id}")
        
        print("in clientwidget_updated flush_to_db: ", room_id, instance.room_id, variables)
        instance.messages.extend(fetch_history_from_redis(instance.room_id, post_delete=False))
        instance.recent_messages.extend(fetch_history_from_redis(instance.room_id, post_delete=True))
        
        if is_lead is not None:
            instance.is_lead = is_lead

        if bot_type == "website":
            instance.save(using=db_label)
        else:
            print("here")
            instance.bot_is_active = False
            instance.end_time = timezone.now()
            instance.save(using=db_label, send_update=True)
            print("there", instance.bot_is_active, instance.is_lead)


@shared_task
def adding_task(x, y):
    """
        Dummy addition task to test working of celery
    """
    return x + y


@shared_task
def send_user_message(groups, event={}, data={}, store_full=False):
    """
        Sends the LiveChat message using websockets via Celery
    """
    for group in groups:
        async_to_sync(channel_layer.group_send)(
            group,
            {
                'type': 'chat_message',
                **event,
            }
        )
    
    if 'room_id' in event:
        append_msg_to_redis(event['room_id'], data, store_full=store_full)
        num_msgs = cache.get(f"CLIENTWIDGET_COUNT_{event['room_id']}", 0)
        num_msgs += 1
        cache.set(f"CLIENTWIDGET_COUNT_{event['room_id']}", num_msgs, timeout=lock_timeout + BUFFER_TIME)


@shared_task
def send_template_message(sender_group, receiver_group, reply, room_name, store_full=False):
    """
        Sends the Template Message using websockets via Celery
    """
    async_to_sync(channel_layer.group_send)(
        sender_group, {
            'type': 'template_message',
            **reply,
        }
    )

    if room_name is not None:
        async_to_sync(channel_layer.group_send)(
            receiver_group, {
                'type': 'template_message',
                **reply,
            }
        )

    # Append the BOT response to Redis List
    append_msg_to_redis(room_name, reply, store_full=store_full)


@shared_task
def send_from_api_task(message: str, room_name: str, user: str = None):
    """Sends a message from the API to a Websocket consumer

    Args:
        message (str): The message content
        room_name (str): The name of the chat room
        user (str, optional): The name of the user. Defaults to None.
    """
    group_name = 'chat_%s' % room_name
    
    # We can directly send a message to this group
    # only if nobody is there. So check the lock
    # TODO: Check this atomically
    lock = cache.get(f'CLIENTWIDGETROOMLOCK_{room_name}')
    
    if lock == True:
        async_to_sync(channel_layer.group_send)(
        group_name,
        {
            "type": "chat_message",
            "message": message,
            'room_name': room_name,
            'time': datetime.utcnow().strftime("%d/%m/%Y %H:%M:%S"),
            'user': user
        })
    else:
        # Nobody there. Directly save it to the cache
        pass
    
    # Save the message (in both cases)
    if user == 'bot_parsed':
        append_msg_to_redis(room_name, message)
    else:
        append_msg_to_redis(room_name, {
                'user': user,
                'time': datetime.utcnow().strftime("%d/%m/%Y %H:%M:%S"),
                'room_name': room_name,
                'message': message,
            },
            store_full=True,
        )


@shared_task
def chat_lead_send_update(room_id, is_lead, data):
    """Sends an Email Update if a lead is encountered during an ongoing live-chat
    """
    ChatRoom = apps.get_model(app_label='clientwidget', model_name='ChatRoom')

    queryset = ChatRoom.objects.filter(pk=room_id, bot_is_active=True)
    if queryset.count() == 0:
        return
    
    chatroom = queryset.first()

    from_email = config('EMAIL_HOST_USER')
    
    owner = chatroom.bot_info.owner
    if owner is None:
        return
    
    to_email = [owner.email]

    if data is None:
        # Possibly need to fetch from DB
        data = chatroom.variables
    
    if is_lead == True:
        if cache.get(f'CLIENTWIDGETROOMLOCK_{room_id}') is not None:
            # Ongoing chat. Send Email
            messages = fetch_history_from_redis(room_id)
            message = render_to_string('clientwidget/send_lead_encounter_email.html', {'user': owner, 'lead_data': data, 'messages': messages})

            logger.info(f"Lead Encountered! Sending an Email to owner {owner.email}")
            mail_subject = "Clientwidget Lead Encountered"
            send_mail(mail_subject, message, from_email, to_email, fail_silently=True, html_message=message)
        else:
            # Chat has completed
            pass
    else:
        if cache.get(f'CLIENTWIDGETROOMLOCK_{room_id}') is not None:
            # Ongoing chat. Send Email
            messages = fetch_history_from_redis(room_id)
            message = render_to_string('clientwidget/send_nonlead_encounter_email.html', {'user': owner, 'nonlead_data': data, 'messages': messages})

            logger.info(f"Non-Lead Encountered. Sending an Email to owner {owner.email}")
            mail_subject = "Clientwidget Anonymous User Encountered"
            send_mail(mail_subject, message, from_email, to_email, fail_silently=True, html_message=message)
        else:
            # Chat has completed
            pass


@shared_task
def send_update(owner_id, field_dict, team_name=None):
    # Status has changed. This is an update
    try:
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f'listing_channel_{owner_id}',
            {
                'type': 'listing_channel_event',
                **field_dict
            }
        )
        if team_name is not None:
            for team in team_name:
                async_to_sync(channel_layer.group_send)(
                    'team_{}_{}'.format(owner_id, str(team)),
                    {
                        'type': 'listing_channel_event',
                        **field_dict,
                    }
                )
    except Exception as ex:
        print(ex)


@shared_task
def flush_session(room_name, room_id, session_end):
    ChatRoom = apps.get_model(app_label='clientwidget', model_name='ChatRoom')

    if not isinstance(room_id, uuid.UUID):
        room_id = uuid.UUID(room_id)
    
    ext = cache.get(str(room_id), "default")
    session_variables = cache.get(f"VARIABLES_{room_name}")
    is_lead = cache.get(f"IS_LEAD_{room_name}")
    if is_lead != True:
        is_lead = False
    if hasattr(settings, 'CELERY_TASK') and settings.CELERY_TASK == True:
        _ = flush_db_task.delay(room_id, 'AnonymousUser', session_variables, is_lead=is_lead, db_label=ext)
    else:
        # Only flush to DB for website bot
        flush_db_task(room_id, 'AnonymousUser', session_variables, is_lead=is_lead, db_label=ext)
    
    # Make the chat inactive
    if (cache.get(f"CLIENTWIDGET_SESSION_END_{room_name}") == True) or (session_end == True):
        # Delete token only if session has ended
        cache.delete(f"CLIENTWIDGET_SESSION_TOKEN_{str(room_id)}")
    
    # Check the takeover flag
    takeover = cache.get(f"CLIENTWIDGET_TAKEOVER_{room_name}")
    num_msgs = cache.get(f"CLIENTWIDGET_COUNT_{room_name}", 0)

    with transaction.atomic():
        if room_id is None:
            queryset = ChatRoom.objects.using(ext).filter(room_name=room_name)
        else:
            queryset = ChatRoom.objects.using(ext).filter(room_id=room_id)
        if queryset.count() == 1:
            instance = queryset.first()
            instance.bot_is_active = False
            instance.num_msgs = num_msgs
            if hasattr(instance, 'end_time'):
                instance.end_time = datetime.utcnow()
            if takeover == True:
                instance.takeover = True
            instance.save(send_update=True, using=ext)
    
    # Delete the locks
    cache.delete(f'CLIENTWIDGETROOMLOCK_{room_name}') # Lock for the room
    cache.delete(f'CLIENTWIDGETLOCK_{room_name}') # Lock for the room messages
    cache.delete(f"CLIENTWIDGETTIMEOUT_{room_name}")

    # Delete the expiry lock
    cache.delete(f"CLIENTWIDGET_EXPIRY_LOCK_{room_name}")

    if (cache.get(f"CLIENTWIDGET_SESSION_END_{room_name}") == True) or (session_end == True):
        # Only if session has ended
        # Delete the chat information
        cache.delete(f"CLIENTWIDGET_SESSION_END_{room_name}")
        cache.delete(f"CLIENTWIDGET_TAKEOVER_{room_name}")
        cache.delete(f"CLIENTWIDGET_COUNT_{room_name}")
        cache.delete(f'CLIENTWIDGETLEADFIELDS_{room_name}')
        cache.delete(f"CLIENTWIDGETLEADDATA_{room_name}")
        cache.delete(f'CLIENTWIDGETROOMINFO_{room_name}')
        cache.delete(f"CLIENTWIDGETSUBSCRIBED_{room_name}")
        cache.delete(f"CLIENTWIDGET_USER_LIST_{room_name}")
        cache.delete(f'IS_LEAD_{room_name}')



@shared_task
def check_active_room_status(room_id, bot_type='website'):
    """Periodically checks the status of an active room and deactivates it if no messages are received over a certain period of time
    """
    from .views import BUFFER_TIME, lock_timeout
    if bot_type == 'website':
        lock = cache.get(f"CLIENTWIDGETROOMLOCK_{room_id}")
        if lock is None:
            return
        
        # Check the latest timestamp
        latest_timestamp = cache.set(f"CLIENTWIDGETTIMEOUT_{room_id}", datetime.utcnow().strftime("%d/%m/%Y %H:%M:%S"), timeout=lock_timeout)
        if latest_timestamp is None:
            # Expired
            return
        
        # Convert to datetime
        latest_timestamp = datetime.strptime(latest_timestamp, "%d/%m/%Y %H:%M:%S")

        delta = (datetime.utcnow() - latest_timestamp).seconds

        if delta >= 100:
            # 100 seconds make it inactive
            pass


@shared_task
def update_operator_mappings(owner_id, assigned_operator_id, room_id, status, team_name=None):
    from .views import BUFFER_TIME, lock_timeout
    if room_id is None:
        return
    
    if status is None:
        return
    
    if status in ['pending']:
        # Insert items into the mapping
        print(f"Insert {len(assigned_operator_id)} members to Room {room_id}")

        if team_name is not None:
            cache.set(f"TEAM_{room_id}", team_name, timeout=lock_timeout + BUFFER_TIME)
                
            
        owner_map = cache.get(f"OWNER_MAP_{owner_id}")
        if owner_map is None:
            for assigned_operator in assigned_operator_id:
                owner_map = {str(assigned_operator): str(room_id)}

                #TODO: need to change this to: owner_map = {str(room_id): assigned_operator_id} for efficiency
        else:
            for assigned_operator in assigned_operator_id:
                owner_map[str(assigned_operator)] = str(room_id)
            
        cache.set(f"OWNER_MAP_{owner_id}", owner_map, timeout=lock_timeout + BUFFER_TIME)

        client_map = cache.get(f"CLIENT_MAP_{owner_id}")
        if client_map is None:
            client_map = {str(room_id): assigned_operator_id}
        else:    
            client_map[str(room_id)] = assigned_operator_id
        cache.set(f"CLIENT_MAP_{owner_id}", client_map, timeout=lock_timeout + BUFFER_TIME)

        #operator_map = cache.get(f"OPERATOR_MAP_{assigned_operator_id}")
        #if operator_map is None:
        #    operator_map = {str(owner_id): str(room_id)}
        #else:
        #    owner_map[str(owner_id)] = str(room_id)
        #cache.set(f"OPERATOR_MAP_{assigned_operator_id}", operator_map, timeout=lock_timeout + BUFFER_TIME)
    
    elif status in ['resolve', 'disconnected']:
        # Remove items from the mapping
        owner_map = cache.get(f"OWNER_MAP_{owner_id}")
        if owner_map is None:
            pass
        else:
            try:
                for assigned_operator in assigned_operator_id:
                    del owner_map[str(assigned_operator)]
                    cache.set(f"OWNER_MAP_{owner_id}", owner_map, timeout=lock_timeout + BUFFER_TIME)
            except:
                pass
        
        client_map = cache.get(f"CLIENT_MAP_{owner_id}")
        if client_map is None:
            pass
        else:
            try:
                del client_map[str(room_id)]
                for assigned_operator in assigned_operator_id:
                    cache.set(f"CLIENT_MAP_{assigned_operator}", client_map, timeout=lock_timeout + BUFFER_TIME)
            except:
                pass

