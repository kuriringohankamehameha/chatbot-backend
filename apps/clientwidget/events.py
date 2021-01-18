"""
clientwidget/events.py

Contains the necessary functions for handling events on the Server side.

We use a Redis Store for storing the session data, and use PostgreSQL as the persistent DB.
"""

import datetime
import json
import os
import random
import string
import traceback
import uuid
from itertools import zip_longest

import requests
# Celery related imports
from celery import task
from coolname import generate_slug
# from celery import current_app
from decouple import Config, RepositoryEnv, UndefinedValueError
from django.apps import apps
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.utils import timezone
from redis import StrictRedis, WatchError

from apps.accounts.models import User
from apps.clientwidget.models import ChatRoom

from .exceptions import logger
from .views import WEBHOOK_TIMEOUT

# from .tasks import celery

Chatbox = apps.get_model(app_label='chatbox', model_name='Chatbox')


# Define a Decorator for making uuid objects to string automatically
def uuid_to_string(func): 
    def wrapper(*args, **kwargs):
        if 'room_name' in kwargs:
            if isinstance(kwargs['room_name'], uuid.UUID):
                # Convert room_id to str
                kwargs['room_name'] = str(kwargs['room_name'])
        else:
            # room_name is taken as FIRST argument
            if len(args) > 0 and isinstance(args[0], uuid.UUID):
                # Convert room_id to str
                args = list(args)
                args[0] = str(args[0])
        return func(*args, **kwargs)  
    return wrapper 


def fetch_redis_batch(redis_iterable, batch_size):
    """
        Get a batch of keys from the redis store, as a list of iterators
    """
    # Fetch all the keys and values in a batch
    keys = [iter(redis_iterable)] * batch_size
    return zip_longest(*keys)


@uuid_to_string
def flush_session(room_name, batch_size):
    """
        Deletes the messages related to the session on the redis cache
    """
    # Flush the contents of the redis cache for this session
    REDIS_CONNECTION = cache.get_client('')
    for key_batch in fetch_redis_batch(
            REDIS_CONNECTION.scan_iter(cache.make_key(f"{room_name}_*")), batch_size
        ):
        for key in key_batch:
            if key is None:
                break
            REDIS_CONNECTION.delete(key)


@uuid_to_string
def update_session_redis(room_name, msg_number, content):
    """
        Sets the key-value fields for a message on the redis store
    """
    REDIS_CONNECTION = cache.get_client('')
    REDIS_CONNECTION.hmset(room_name + "_" + str(msg_number), content)
    # Also update the history
    # TODO: Store it as a single nested hash value
    REDIS_CONNECTION.hmset(cache.make_key(f"HISTORY_{room_name}_{msg_number % (N)}"), content)


def atomic_set(key, value, timeout=24 * 60 * 60):
    """
        Atomically sets {key: value} on the redis store
    """
    REDIS_CONNECTION = cache.get_client('')
    try:
        with REDIS_CONNECTION.pipeline() as pipe:
            try:
                pipe.watch(key)
                pipe.multi()
                pipe.set(key, value)
                pipe.expire(key, timeout)
                pipe.get(key)
                return pipe.execute()[-1], False
            except WatchError:
                return pipe.get(key), True
    except TypeError:
        return REDIS_CONNECTION.get(key), True


def atomic_get(key):
    """
        Atomically gets the most recent {key : value} pair from the redis store
    """
    REDIS_CONNECTION = cache.get_client('')
    try:
        with REDIS_CONNECTION.pipeline() as pipe:
            try:
                pipe.watch(key)
                pipe.multi()
                pipe.get(key)
                return pipe.execute()[-1], False
            except WatchError:
                return pipe.get(key), True
    except TypeError:
        return REDIS_CONNECTION.get(key), True


def get_variables(bot_variable_json: dict) -> dict:
    """Fetch the empty variable dictionary from `bot_variable_json`

    Args:
        bot_variable_json (dict) : Variable Bot Dictionary of the format `{'dsds3432f': '@name'}`

    Returns:
        dict: A dictionary of the format `{"@name": "", "@email": ""}`
    """

    # This function is not needed anymore. Now returning back the input
    return bot_variable_json


def get_channel_id(room_id):
    # Return channel id from room_id
    instance = ChatRoom.objects.filter(pk=room_id).first()
    if not instance:
        return None
    else:
        return instance.channel_id


def create_room(user, content, bot_id=None, room_name=None, preview=False, standalone=False):
    """
        Creates a new room on the persistent Database and returns the ID of the room
    """
    if content['room_name'] == '':
        length = 3
        if room_name is None:
            content['room_name'] = generate_slug(length)
        else:
            content['room_name'] = room_name
    
    chatbox_instance = Chatbox.objects.filter(pk=bot_id).first()

    if chatbox_instance is None:
        return None, None

    if bot_id is not None:
        variable_json = chatbox_instance.bot_variable_json

        # Get the variables from Chatbox.bot_variable_json
        content['variables'] = get_variables(variable_json)
    
    content['created_on'] = timezone.now()
    
    instance = ChatRoom(**content)
    instance.admin_id = chatbox_instance.owner.id
    try:
        with transaction.atomic():
            if room_name is None:
                instance.save(new_visitor=True, using=chatbox_instance.owner.ext_db_label, preview=preview, standalone=standalone)
            else:
                instance.save(using=chatbox_instance.owner.ext_db_label)
        return instance.room_id, instance.room_name
    except IntegrityError:
        print('Room already there in DB!')
        return instance.room_id, instance.room_name


@uuid_to_string
def update_msgcount(room_name, num_msgs):
    """
        Updates the message count shared variable atomically on the redis cache
    """
    while True:
        # Set the current message atomically
        num_msgs, error = atomic_set(cache.make_key(f"CURR_MSG_{room_name}"), num_msgs)
        if not error:
            break
        else:
            # Someone else has updated this first
            num_msgs += 1
    return int(num_msgs)


@uuid_to_string
def get_msgcount(room_name):
    """
        Get the message count shared variable atomically from the redis cache
    """
    num_msgs = None
    while True:
        num_msgs, error = atomic_get(cache.make_key(f"CURR_MSG_{room_name}"))
        if not error:
            break
    if num_msgs is None:
        # The corresponding key doesn't exist in redis yet. Create it
        num_msgs = 0
        num_msgs = update_msgcount(room_name, num_msgs)
    return int(num_msgs)


@uuid_to_string
def get_usercount(room_name):
    """
        Get the user count shared variable atomically from the redis cache
    """
    num_users = None
    while True:
        num_users, error = atomic_get(cache.make_key(f"NUM_USERS_{room_name}"))
        if not error:
            break
    if num_users is None:
        # The corresponding key doesn't exist in redis yet. Create it
        num_users = 0
        while True:
            num_users, error = atomic_set(room_name, num_users)
            if not error:
                break
    return int(num_users)


@uuid_to_string
def increment_usercount(room_name):
    """
        Increments the user count shared variable atomically on the redis cache
    """
    num_users = get_usercount(room_name)
    while True:
        # Set the current message atomically
        num_users, error = atomic_set(cache.make_key(f"NUM_USERS_{room_name}"), num_users+1)
        if not error:
            break
    return int(num_users)


@uuid_to_string
def decrement_usercount(room_name):
    """
        Decrement the room counter atomically whenever a Websocket connection is established
    """
    num_users = get_usercount(room_name)
    while True:
        # Set the current message atomically
        num_users, error = atomic_set(cache.make_key(f"NUM_USERS_{room_name}"), num_users-1)
        if not error:
            break
    return int(num_users)


def append_msg_to_db(room_name, message_dict, db_name='secondary', store_full=False):
    """
        Appends the message to the DB
    """
    if isinstance(room_name, uuid.UUID):
        room_id = room_name
        queryset = ChatRoom.objects.using(db_name).filter(room_id=room_id)
    else:
        room_id = None
        queryset = ChatRoom.objects.using(db_name).filter(room_name=room_name)
    
    if queryset.count() > 0:
        room_object = queryset.first()
        
        if store_full:
            room_object.messages.append(message_dict)
            room_object.save(using=db_name)
            return True, None
        
        if 'message' in message_dict:
            if isinstance(message_dict['message'], list):
                room_object.messages.extend(message_dict['message'])
            else:
                room_object.messages.append(message_dict)
        else:
            room_object.messages.append(message_dict)
        
        room_object.save(using=db_name)
        return True, None
    else:
        if room_id is None:
            return False, f"Room Name {room_name} does not exist"
        else:
            return False, f"Room ID {room_id} does not exist"


@uuid_to_string
def append_msg_to_redis(room_name, message_dict, store_full=False, timeout=24 * 60 * 60):
    """
        Appends the message dictionary from the websocket to the Redis Message List
    """
    REDIS_CONNECTION = cache.get_client('')

    if store_full:
        REDIS_CONNECTION.rpush(cache.make_key(f'HISTORY_{room_name}'), json.dumps(message_dict))
        REDIS_CONNECTION.expire(cache.make_key(f'HISTORY_{room_name}'), timeout)
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
    
    REDIS_CONNECTION.expire(cache.make_key(f'HISTORY_{room_name}'), timeout)
    
    # Finally set a lock on this room name. We'll need it later for flushing to DB
    cache.set(f'CLIENTWIDGETLOCK_{room_name}', room_name, timeout=timeout)


@uuid_to_string
def fetch_variables_from_redis(room_name, override=False, bot_type='website'):
    """
        Fetches all the variables from the current session, for `room_name`.
    """
    # Get the lock from the cache
    if override == False:
        lock = cache.get(f"CLIENTWIDGETROOMLOCK_{room_name}")
    else:
        # Let's override this manually
        lock = True

    if bot_type != 'website':
        
        variables = cache.get(f"VARIABLES_{room_name}") 
        return True, variables
        

    if lock == True:
        # Ensure that the lock is set
        variables = cache.get(f"VARIABLES_{room_name}")
        return True, variables
    else:
        # No lock. Session doesn't exist
        return False, f"No currently active sessions for the room {room_name}"


def fetch_variables_from_db(room_name, db_name='default'):
    """
        Fetches all the variables from the DB, for `room_name`.
    """
    try:
        room_id = uuid.UUID(str(room_name))
    except ValueError:
        room_id = None
    
    if room_id is None:
        queryset = ChatRoom.objects.using(db_name).filter(room_name=room_name)
    else:
        queryset = ChatRoom.objects.using(db_name).filter(room_id=room_id)
    
    if queryset.count() == 0:
        if room_id is None:
            return False, f"Room Name {room_name} not found in DB"
        else:
            return False, f"Room ID {room_id} not found in DB"
    
    instance = queryset.first()
    return True, instance.variables


def fetch_recent_history_from_db(room_name, num_msgs=None, db_name='default'):
    """
        Fetches the recent messages from the DB
    """
    if isinstance(room_name, uuid.UUID):
        room_id = room_name
        room_name = str(room_name)
    else:
        room_id = None
    
    if room_id is not None:
        queryset = ChatRoom.objects.using(db_name).filter(room_id=room_id)
    else:
        queryset = ChatRoom.objects.using(db_name).filter(room_name=room_name)
    
    if queryset.count() == 0:
        if room_id is not None:
            return False, f"Room ID {room_id} not found in DB"
        else:
            return False, f"Room Name {room_name} not found in DB"
    
    instance = queryset.first()
    if num_msgs is None:
        return True, instance.recent_messages
    else:
        # Get last num_msgs from the DB
        if num_msgs < 0:
            return False, f"Wrong value. num_msgs is {num_msgs}. Expected a positive integer"
        return True, instance.recent_messages[-num_msgs:]


def fetch_history_from_db(room_name, num_msgs=None, db_name='default'):
    """
        Fetches the messages from the DB
    """
    if isinstance(room_name, uuid.UUID):
        room_id = room_name
        room_name = str(room_name)
    else:
        room_id = None
    
    if room_id is not None:
        queryset = ChatRoom.objects.using(db_name).filter(room_id=room_id)
    else:
        queryset = ChatRoom.objects.using(db_name).filter(room_name=room_name)
    
    if queryset.count() == 0:
        if room_id is not None:
            return False, f"Room ID {room_id} not found in DB"
        else:
            return False, f"Room Name {room_name} not found in DB"
    
    instance = queryset.first()
    if num_msgs is None:
        return True, instance.messages
    else:
        # Get last num_msgs from the DB
        if num_msgs < 0:
            return False, f"Wrong value. num_msgs is {num_msgs}. Expected a positive integer"
        return True, instance.messages[-num_msgs:]


@uuid_to_string
def fetch_history_from_redis(room_name, num_msgs=None, post_delete=False):
    """
        Fetches the most recent num_msgs from Redis on a particular room
    """
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
    return history


@uuid_to_string
def delete_history_from_redis(room_name, num_msgs=None):
    """
        Deletes history from the Redis Cache
    """
    REDIS_CONNECTION = cache.get_client('')
    if num_msgs is None:
        res = REDIS_CONNECTION.delete(cache.make_key(f'HISTORY_{room_name}'))
    else:
        if num_msgs <= 0:
            return 1, None
        else:
            res = REDIS_CONNECTION.ltrim(cache.make_key(f'HISTORY_{room_name}'), num_msgs, -1)
    return res, None


def delete_history_from_db(room_name, num_msgs=None):
    """
        Deletes history from the DB
    """
    if isinstance(room_name, uuid.UUID):
        room_id = room_name
        room_name = str(room_name)
        queryset = ChatRoom.objects.filter(room_id=room_id)
    else:
        room_id = None
        queryset = ChatRoom.objects.filter(room_name=room_name)
    
    if queryset.count() == 0:
        if room_id is None:
            return False, f"Room Name {room_name} not there in DB"
        else:
            return False, f"Room ID {room_id} not there in DB"
    
    instance = queryset.first()
    if num_msgs is None:
        # Delete all messages + variables
        instance.messages = []
        instance.variables = []
        instance.save()
    else:
        # Remove last num_msgs + variables
        instance.messages = instance.messages[:-num_msgs or None]
        instance.variables = []
        instance.save()
    return True, None


def flush_to_db(room_id, user, session_variables, is_lead=None, bot_type="website", other_db=""):
    """
        Appends the session messages and variable content to the database.
    """
    with transaction.atomic():
        ext = cache.get(str(room_id))
        instance = ChatRoom.objects.using(ext).get(pk=room_id)
        if session_variables is not None:
            instance.variables = session_variables
        instance.messages.extend(fetch_history_from_redis(instance.room_id, post_delete=False))
        instance.recent_messages.extend(fetch_history_from_redis(instance.room_id, post_delete=True))
        if is_lead is not None:
            instance.is_lead = is_lead
        if bot_type == "website":
            instance.save(using=ext)
        else:
            ext = other_db
            instance.bot_is_active = False
            instance.end_time = timezone.now()
            instance.save(using=ext, send_update=True)


@uuid_to_string
def cleanup_room_redis(room_name, reset_count=False, bot_type="website"):
    """Dumps the session content of the room into the DB
    """
    connection = cache.get_client('')

    ext = cache.get(str(room_name), "default")

    # Get the room lock status from the cache
    lock = cache.get(f'CLIENTWIDGETROOMLOCK_{room_name}')

    if lock is None and bot_type=="website":
        return

    if lock == True or bot_type in ("whatsapp", "facebook",):
        # Dump to DB
        variables = cache.get("VARIABLES_" + room_name)
        messages_bytes = connection.lrange(cache.make_key("HISTORY_" + room_name), 0, -1)
        messages = list(json.loads(message) for message in messages_bytes)
        modified = False
        
        with transaction.atomic():
            try:
                room_id = uuid.UUID(str(room_name))
                instance = ChatRoom.objects.get(room_id=room_id)
            except ValueError:
                instance = ChatRoom.objects.get(room_name=room_name)
            if variables is not None:
                instance.variables = variables
                modified = True
            if messages is not None:
                if messages != []:
                    instance.messages.extend(messages)
                    if bot_type == 'website' and hasattr(instance, 'recent_messages') and isinstance(getattr(instance, 'recent_messages'), list):
                        instance.recent_messages.extend(messages)
                    modified = True
            if modified:
                instance.bot_is_active = False
                instance.end_time = timezone.now()
                instance.save(using=ext)

    if reset_count == True:
        # Reset the count to 0
        cache.set(f"NUM_USERS_{room_name}", 0)
        # Delete the locks
        cache.delete(f'CLIENTWIDGETROOMLOCK_{room_name}')
        cache.delete(f'CLIENTWIDGETLOCK_{room_name}')

    # Delete the session history
    cache.delete(f"HISTORY_{room_name}")
    cache.delete(f"VARIABLES_{room_name}")


@uuid_to_string
def reset_chatroom_state(room_id, bot_type="website", db_label="default"):
    # if bot_type != "website":
    #     return
    instance = ChatRoom.objects.using(db_label).filter(room_id=room_id).first()
    if instance is None:
        print(f"No such room id {room_id} - Couldn't reset state")
        return
    
    try:
        admin = User.objects.get(id=instance.admin_id)
        cache.delete(f"CLIENT_MAP_{str(admin.uuid)}")
        cache.delete(f"TEAM_{str(instance.room_id)}")
    except Exception as e:
        pass    
    instance.bot_is_active = True
    instance.takeover = False
    instance.status = 'unassgined'
    instance.assignment_type = ''
    instance.assigned_operator = None
    instance.team_assignment_type = None
    instance.assigned_team = None
    instance.end_chat = False
    if hasattr(instance, 'updated_on'):
        instance.updated_on = timezone.now()

    instance.save(using=db_label, send_update=True)
    return


@uuid_to_string
def set_session_variable(room_name, key, value, bot_type="website"):
    variables = cache.get(f"VARIABLES_{room_name}", {})
    variables[key] = value
    cache.set(f"VARIABLES_{room_name}", variables)      


@uuid_to_string
def add_new_variable(room_name, key, value, bot_id, bot_type='website'):
    try:
        if bot_type == "website":
            # Update variable_columns field in Chatbox
            chatbox = Chatbox.objects.filter(pk=bot_id).first()
            if chatbox is None:
                logger.warning(f"No such bot - {bot_id}")
                return
            
            variable_columns = chatbox.variable_columns
            if variable_columns is None:
                variable_columns = list()
            variable_columns = list(set().union(*[variable_columns, [key]]))
            chatbox.variable_columns = variable_columns
            chatbox.save()
            
            # Now set the new session variable
            set_session_variable(room_name, key, value, bot_type)
        else:
            # TODO: Add this for other bots
            return
    except Exception as ex:
        logger.critical(f"Error when adding a new variable: {ex}")
        return


def make_substitution(items, room_id, bot_type='website'):
    result = {}
    if not isinstance(items, list):
        # Single Dict
        if not isinstance(items, dict):
            return result, False
        
        _, variables = fetch_variables_from_redis(room_id, override=True, bot_type=bot_type)
        
        if variables is None:
            variables = {}
        for key, variable in items.items():
            # Try for a variable substitution
            if variable in variables:
                # Do a variable substitution
                result[key] = variables[variable]
            else:
                try:
                    result[key] = variable
                except:
                    result[key] = ""
        return result, True
    else:
        return result, False            


@task
def parse_response(room_id, bot_id, owner_id, bot_type='website', content={}, response_template={}):
    # Response Template: {"name": "@name"}
    if (content in ({}, None,)) or (response_template in ({}, None)):
        return

    serialized_response = content

    logger.info(f"Response Template: {response_template}")
    logger.info(f"Content: {content}")

    if not isinstance(content, (dict,)):
        # Unsupported format. We only support a single JSON Object as a response
        raise ValueError(f"Response type is unsupported. Only a single JSON object is allowed")

    _, session_variables = fetch_variables_from_redis(room_id, override=True, bot_type=bot_type)
    
    for key, value in serialized_response.items():
        # Match with variables
        if key in response_template and response_template[key] in session_variables:
            set_session_variable(room_id, response_template[key], value)
        else:
            if key in response_template and response_template[key] not in session_variables and response_template[key].startswith("@"):
                # New Variable Data
                pass
                # logger.info(f"Adding a new variable: {key}")
                # add_new_variable(room_id, response_template[key], value, bot_id, bot_type=bot_type)
            else:
                # Non-variable data. Ignore it
                continue
    return  


@task
def send_to_webhook(room_id, bot_id, owner_id, webhook_url, request_type='POST', request_headers={}, query_params=None, request_payload=None, response_template={}, timeout=WEBHOOK_TIMEOUT, bot_type='website', blocking=True):
    response = None

    try:
        if timeout is None:
            timeout = WEBHOOK_TIMEOUT
        
        request_type = request_type.lower()
        
        query_params, status = make_substitution(query_params, room_id, bot_type)

        if not status:
            logger.info("Error during substitution of query params")

        request_payload, status = make_substitution(request_payload, room_id, bot_type)

        if not status:
            logger.info("Error during substitution of request payload")
        
        session = requests.Session()
        
        if request_headers in (None, {},):
            session.headers.update({"Content-Type": "application/json",})
        else:
            session.headers.update(request_headers)

        if request_type in ['post', 'put']:
            if session.headers.get('Content-Type') == 'application/json':
                response = getattr(session, request_type)(webhook_url, json=request_payload, timeout=timeout)
            else:
                response = getattr(session, request_type)(webhook_url, data=request_payload, timeout=timeout)
        
        elif request_type in ['get',]:
            url = webhook_url
            response = getattr(session, request_type)(url, params=query_params, timeout=timeout)
    
    except (requests.exceptions.Timeout) as timeoutexc:
        logger.critical(f"Timeout Exception: {timeoutexc}")
    
    except Exception as ex:
        logger.critical(f"Exception: {ex}")
    
    if hasattr(response, 'content'):
        try:
            content = json.loads(response.content.decode('utf-8'))
        except Exception as decodeex:
            content = None
            traceback.print_exc()
            logger.critical(f"Error during decoding: {decodeex}")
    else:
        content = None
    
    try:
        # Now parse the incoming response
        _ = parse_response(room_id, bot_id, owner_id, bot_type, content=content, response_template=response_template)
        parsed_status = True
    except Exception as ex:
        parsed_status = False
        logger.critical(f"Exception when parsing response: {ex}")
    
    return response, parsed_status


def process_webhook_node(room_id, bot_id, bot_component_response, owner_id, bot_type='website'):
    # Send to the webhook URI
    webhook_url = bot_component_response.get('webhookUrl')
    request_type = bot_component_response.get('requestType')
    is_blocking_component = bot_component_response.get('blocking', True)
    router = bot_component_response.get('routing', {})
    try:
        timeout = float(bot_component_response.get('timeout', WEBHOOK_TIMEOUT))
    except:
        timeout = float(WEBHOOK_TIMEOUT)

    query_params = bot_component_response.get('queryParams') if bot_component_response.get('customize' + 'queryParams') == True else None
    request_payload = bot_component_response.get('requestBody') if bot_component_response.get('customize' + 'requestBody') == True else None
    request_headers = bot_component_response.get('requestHeaders') if bot_component_response.get('customize' + 'requestHeaders') == True else None
    response_template = bot_component_response.get('responseBody') if bot_component_response.get('customize' + 'responseBody') == True else None

    parsed_status = None
    response = None
    
    if (is_blocking_component == True) or (response_template not in ({}, None,)):
        response, parsed_status = send_to_webhook(room_id, bot_id, owner_id, webhook_url, request_type=request_type, request_headers=request_headers, query_params=query_params, request_payload=request_payload, response_template=response_template, timeout=timeout, bot_type=bot_type)
        try:
            code = response.status_code
            content = response.content
            target_id = router.get(str(code), router.get('default'))
            logger.info(f"Routing to {target_id} from WEBHOOK Component for code: {code}")
            if parsed_status != False:
                return target_id, content
            else:
                raise ValueError(f"Unsupported Response Type. Cannot parse this response")
        except Exception as ex:
            logger.critical(f"Error during Webhook routing: {ex}")
    else:
        try:
            _, _ = send_to_webhook.delay(room_id, bot_id, owner_id, webhook_url, request_type=request_type, request_headers=request_headers, query_params=query_params, request_payload=request_payload, response_template=response_template, timeout=timeout, bot_type=bot_type)
            target_id = router.get('default')
            logger.info(f"Routing to {target_id} from WEBHOOK Component for NON BLOCKING CODE")
            return target_id, None
        except Exception as ex:
            logger.critical(f"Error during Webhook routing: {ex}")
    
    if response is None:
        logger.warning(f"Webhook Sending failed")
        content = None
    else:
        logger.warning(f"Webhook component failed to parse the response")
        content = response.content

    # Route to the error handling component
    try:
        target_id = router.get('error', router.get('default'))
        logger.info(f"Routing to {target_id} from WEBHOOK Component for code: ERROR")
        return target_id, content
    except Exception as ex:
        logger.critical(f"Error during request exception handling: {ex}")
    
    return None, None


def variable_typecast(variable, variable_type):
    if variable_type == 'string':
        variable = "\"" + variable + "\""
    elif variable_type == 'datetime':
        if len(variable.split()) > 1:
            variable = f"datetime.datetime.strptime(\"{variable}\", '%d-%m-%Y %H:%M:%S')"
        else:
            variable = f"datetime.datetime.strptime(\"{variable}\", '%d-%m-%Y')"
    elif variable_type == 'int':
        variable = str(int(variable))
    elif variable_type == 'float':
        variable = str(float(variable))
    elif variable_type == 'bool':
        variable = str(bool(variable))
    return variable


def cast_expression(expression_value, expression_type):
    if expression_type == 'datetime':
        try:
            expression_value = datetime.datetime.strftime(expression_value, '%d-%m-%Y %H:%M:%S')
        except:
            expression_value = datetime.datetime.strftime(expression_value, '%d-%m-%Y')
    elif expression_type in ['int', 'float', 'bool',]:
        expression_value = str(expression_value)
    return expression_value


def parse_set_variable_expression(room_id, bot_id, bot_component_response, owner_id, bot_type='website'):
    variable = bot_component_response.get('variable')
    variable_type = bot_component_response.get('variableType', 'string')
    tokens = bot_component_response.get('tokens', [])
    router = bot_component_response.get('routing', {})

    try:
        _, session_variables = fetch_variables_from_redis(room_id, override=True, bot_type=bot_type)

        expression_value = None
        
        expression_string = "expression_value="

        for token in tokens:
            if (token['type'] != "IDENTIFIER"):
                if token['type'] == 'STRING':
                    value = token['value'].replace("'", "\"")
                    expression_string += value
                elif token['type'] == 'DATE':
                    if len(token['value'].split()) > 1:
                        value = f"datetime.datetime.strptime({token['value']}, '%d-%m-%Y %H:%M:%S')"
                    else:
                        value = f"datetime.datetime.strptime({token['value']}, '%d-%m-%Y')"
                    expression_string += value
                elif token['type'] == 'TIME':
                    # datetime object can also be of the form: 2 days, 12:40:00
                    tmp = token['value'].split(",", 1)
                    if len(tmp) == 2:
                        days = int(tmp[0].split()[0])
                        hours, minutes, seconds = (int(i) for i in tmp[1].split(":"))
                    else:
                        days = 0
                        hours, minutes, seconds = (int(i) for i in token['value'].split(":"))
                    value = f"datetime.timedelta(days={days}, hours={hours}, minutes={minutes}, seconds={seconds})"
                    expression_string += value
                else:
                    expression_string += token['value']
            else:
                value = variable_typecast(session_variables.get(token['value']), variable_type)
                expression_string += value
        
        try:
            local_namespace = {}
            if variable_type == 'datetime':
                expression_string = 'import datetime;' + expression_string
            exec(expression_string, {}, local_namespace)
            expression_value = local_namespace['expression_value']
        except Exception as ex:
            logger.critical(f"Exception during set variable: {ex}")
        
        logger.info(f"Expression string: {expression_string}")
        logger.info(f"After variable set, value = {expression_value}")
        
        if expression_value is not None:
            expression_value = cast_expression(expression_value, variable_type)
            set_session_variable(room_id, variable, expression_value, bot_type="website")
        else:
            raise ValueError(f"Expression is None")

        target_id = router.get('success')
        
        return target_id, variable, expression_value
    
    except Exception as ex:
        logger.critical(f"Exception with Set Variable: {ex}")
        target_id = router.get('error', None)
        return target_id, None, None
