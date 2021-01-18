import copy
import json
import os
import random
import re
import string
import time
import uuid
from datetime import date, datetime, timedelta
from itertools import chain

from decouple import UndefinedValueError, config
from django.apps import apps
from django.conf import settings
from django.core import management
from django.core.cache import cache
from django.core.management import call_command
from django.db.models import Count, F
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, permissions, serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.chatbox.bot_json_parser import BotJSONParser
from apps.chatbox.parse_json import parse_json
from apps.clientwidget.models import ChatRoom, ChatSession
from apps.clientwidget.serializers import (ActiveChatRoomSerializer,
                                           VariableSerializer)
from apps.taskscheduler.schedule_manager.management import DEVELOPMENT

from . import serializers, tasks
from .consumers import ClientWidgetConsumer
from .events import (cleanup_room_redis, create_room, delete_history_from_db,
                     delete_history_from_redis, fetch_history_from_db,
                     fetch_history_from_redis, fetch_recent_history_from_db,
                     fetch_variables_from_db, fetch_variables_from_redis,
                     get_variables, reset_chatroom_state)
from .views import BUFFER_TIME, lock_timeout

Chatbox = apps.get_model(app_label='chatbox', model_name='Chatbox')

# Template Chatbot related API starts here

class TemplatePreviewChatbot(APIView):
    """API for dealing with the Chatbot preview.

    Endpoint URL:
        api/clientwidget/session/preview/<bot_id>    
    """

    def get_bot_data(self, bot_id, bot_com_tid=None):
        # Use Redis as an in-memory cache
        if isinstance(bot_id, uuid.UUID):
            bot_id = str(bot_id)
        content = cache.get(f'BOT_PREVIEW_{bot_id}')
        variable_data = {}
        if content == {} or content is None:
            raise Http404
        else:
            variables = cache.get(f'BOT_PREVIEW_VARIABLE_{bot_id}')
            if variables == {} or variables is None:
                pass
            else:
                variable_data = json.loads(variables)
            content = json.loads(content)
            if bot_com_tid:
                for key_id in content:
                    if key_id == bot_com_tid:
                        bot_component_response = content[key_id]
                        return bot_component_response, variable_data
                raise Http404
            else:
                for key_id in content:
                    if content[key_id]['nodeType'] == 'INIT':
                        bot_component_response = content[key_id]
                        return bot_component_response, variable_data
                raise Http404


    def get(self, request, bot_id: uuid.UUID, format=None) -> Response:
        """GET Request handler for the preview Chatbot.

        Args:
            request : The `request` object
            bot_id (uuid.UUID): The bot_hash id
            format (optional): The format type. Defaults to `None`.

        Returns:
            Response: A `Response` object of the form `{bot_data, 'variables': {'@name': 'xyz'}}`
        """
        if isinstance(bot_id, uuid.UUID):
            bot_id = str(bot_id) # type: ignore
        bot_obj, variable_obj = self.get_bot_data(bot_id)

        if variable_obj is not None:
            bot_obj = {**bot_obj, 'variables': variable_obj}
            return Response(bot_obj)
        else:
            bot_obj = {**bot_obj, 'variables': {}}
            return Response(bot_obj)

    def post(self, request, bot_id, format=None):
        """Post API for the template chatbot preview.

        Request Format:
        * For the first time, you MUST send the `bot_full_json` as part of the request. Since the preview is in-memory, the bot information is not stored anywhere, and the full bot json is needed.

        So, the first POST request will be:
        {
            "bot_full_json": {...}
        }

        * After the `bot_full_json` has been stored to the cache, you can now send only the `target_id`s.

        Subsequent requests are of the given form:
        {
            "target_id": "b6514efe-c838-4b14-a5ec-65fd30238184",
            "variable": "@name",
            "post_data": "xyz"
        }

        Here, "variable" and "post_data" are optional, and needed only for variable data input.

        Response Format:
        The response will always be of the below format:
        {
            "id": "b6514efe-c838-4b14-a5ec-65fd30238184",
            "icon": "message",
            "message": true,
            "messages": [
                "Thanks @name"
            ],
            "nodeType": "MESSAGE",
            "targetId": "db1beb61-2b5b-4d05-9533-b5906c53d006",
            "variables": {
                "@name": "xyz"
            }
        }
        """
        if isinstance(bot_id, uuid.UUID):
            bot_id = str(bot_id)
        if 'bot_full_json' in request.data:
            # Dump to the Redis Cache
            parser = BotJSONParser()
            bot_json, variable_json, _, _ = parser.parse_json(request.data['bot_full_json'])
            bot_json, variable_json = json.dumps(bot_json), json.dumps(variable_json)
            if bot_json is None or bot_json == {}:
                return Response(status=status.HTTP_400_BAD_REQUEST)
            if variable_json is None or variable_json == {}:
                pass
            else:
                cache.set(f"BOT_PREVIEW_VARIABLE_{bot_id}", variable_json)
            cache.set(f"BOT_PREVIEW_{bot_id}", bot_json)
            # Not send the INIT data
            bot_obj, variable_obj = self.get_bot_data(bot_id, None)
            return Response({**bot_obj, 'variables': variable_obj}, status=status.HTTP_200_OK)
        elif 'target_id' in request.data:
            # Get the target_id message from Redis
            tid = request.data['target_id']
            content = cache.get(f"BOT_PREVIEW_VARIABLE_{bot_id}")
            if content == {} or content is None:
                pass
            else:
                content = json.loads(content)
                if 'variable' in request.data:
                    if 'post_data' in request.data:
                        if request.data['variable'] in content:
                            # Update to Redis only if the variable name is present
                            content[request.data['variable']] = request.data['post_data']
                            cache.set(f"BOT_PREVIEW_VARIABLE_{bot_id}", json.dumps(content))
                        else:
                            # The variable name doesn't exist
                            return Response(f"Variable field '{request.data['variable']}' doesn't exist.", status=status.HTTP_400_BAD_REQUEST)
            bot_obj, variable_obj = self.get_bot_data(bot_id, tid)
            return Response({**bot_obj, 'variables': variable_obj})
        else:
            return Response(status=status.HTTP_400_BAD_REQUEST)


class TemplateChatbot(APIView):
    """The Template Chatbot API for the web-based chatbot
    """
    def get_bot_data(self, bot_id, bot_com_tid=None, user=None, room_id=None, room_name=None, website_url=None):
        """Fetches the bot data information from `bot_full_json`

        Args:
            bot_id (uuid.UUID): Bot ID of an existing bot
            bot_com_tid (uuid.UUID, optional): The `target_id` node. Defaults to None.
            user (optional): Defaults to None.
            room_id (uuid.UUID, optional): The room ID. Defaults to None if you want to create a new room.
            room_name (str, optional): The room name. Defaults to None if you want to create a new room.

        Raises:
            Http404: If the `bot_id` does not exist in the `Chatbox` model.
        """
        try:
            bot_obj = Chatbox.objects.get(pk=bot_id)
            if not isinstance(bot_obj.bot_data_json, dict):
                raise Http404
            if bot_obj.is_deleted == True:
                raise Http404("No such bot exists")
            reset_state = False
            if bot_com_tid:
                for key_id in bot_obj.bot_data_json:
                    if key_id==bot_com_tid:
                        bot_component_response = bot_obj.bot_data_json[key_id]
                        var_response = bot_obj.bot_variable_json
                        if room_id is not None:
                            bot_component_response['room_id'] = room_id
                            # Make it active again
                            instance = ChatRoom.objects.using(bot_obj.owner.ext_db_label).get(room_id=room_id, admin_id=bot_obj.owner.id)
                            if instance.status in ['resolve', 'disconnected']:
                                # Un-assign this again
                                instance.status = 'unassigned'
                                reset_state = True
                            instance.bot_is_active = True
                            instance.save(using=bot_obj.owner.ext_db_label, send_update=True)
                            if reset_state == False:
                                return bot_component_response, var_response, None, None, bot_obj.owner.uuid
                            else:
                                # Go to INIT again
                                return self.get_bot_data(bot_id, bot_com_tid=None, user='AnonymousUser', room_id=room_id, room_name=room_name, website_url=website_url)
                raise Http404
            else:
                for key_id in bot_obj.bot_data_json:
                    if bot_obj.bot_data_json[key_id]['nodeType'] == 'INIT':
                        bot_component_response = bot_obj.bot_data_json[key_id]
                        if user is not None:
                            if room_id is None:
                                bot_component_response['room_id'], _ = create_room(user, content={
                                    'room_name': '',
                                    'bot_id': str(bot_obj.bot_hash),
                                    'bot_is_active': True,
                                    'num_msgs': 0,
                                    'chatbot_type': bot_obj.chatbot_type,
                                    'website_url': website_url,
                                    'channel_id': website_url,
                                }, bot_id=bot_obj.bot_hash)
                            else:
                                bot_component_response['room_id'] = room_id
                                # Make it active again
                                try:
                                    instance = ChatRoom.objects.using(bot_obj.owner.ext_db_label).get(room_id=room_id, bot_id=bot_obj.bot_hash, admin_id=bot_obj.owner.pk)
                                    if instance.status in ['resolve', 'disconnected']:
                                        # Un-assign this again
                                        instance.status = 'unassigned'
                                        reset_state = True
                                    instance.bot_is_active=True
                                    instance.save(using=bot_obj.owner.ext_db_label, send_update=True)
                                except Exception as e:
                                    print(e)
                        return bot_component_response, bot_obj.bot_variable_json, bot_component_response['room_id'], None, bot_obj.owner.uuid
                raise Http404
        except Chatbox.DoesNotExist:
            raise Http404
    

    def generate_token(self, bot_id=None, room_id=None):
        """Generates an authentication token for the session

        Returns:
            str: A random 64 bit string
        """
        return ''.join(random.choice(string.ascii_letters) for _ in range(64))
    

    def renew_token(self, request=None, bot_id=None, room_id=None):
        """Renews the token for the session
        """
        print("Session has expired. Renewing the session...")

        queryset = ChatSession.objects.filter(room_id=room_id)

        if queryset.count() == 0:
            # New Session
            session_token = self.generate_token(bot_id=bot_id, room_id=room_id)
            _ = ChatSession.objects.create(session_token=session_token, room_id=room_id, ip_address=request.META.get("REMOTE_ADDR"))
            cache.set(f"CLIENTWIDGET_SESSION_TOKEN_{str(room_id)}", session_token, timeout=lock_timeout)
            return session_token

        instance = queryset.first()
        prev_token = instance.session_token
        session_token = self.generate_token(bot_id=bot_id, room_id=room_id)
        
        # Update the token on the DB
        queryset.update(session_token=session_token, updated_on=timezone.now(), prev=prev_token)
        cache.set(f"CLIENTWIDGET_SESSION_TOKEN_{str(room_id)}", session_token, timeout=lock_timeout)
        return session_token

    
    def get(self, request, bot_id, format=None):
        """GET request format:

        To setup the session for the Template Based Chat, you can send an empty GET request. This will return an INIT response from the bot.

        Using the `targetId` node, you can continue the chat by using PUT requests with `target_id`.
        """

        # initialize user id
        if hasattr(request, 'user'):
            user = request.user
        else:
            user = None

        # JSON Serializable format for bot_id
        session_bot_id = str(bot_id)

        if 'bots' not in request.session:
            # Represents a dict of all the bots which the current session
            # has interacted with
            request.session['bots'] = dict()
            request.session.modified = True
        
        session_token = None
        owner_id = None

        website_url = None
        first_visit = True

        if (user is None) or (request.user.is_authenticated == False):
            try:                
                if 'website_url' in request.query_params:
                    temp = request.query_params['website_url']
                
                if temp == 'undefined':
                    pass
                else:
                    website_url = temp

                if website_url is not None and website_url[-1] == '/':
                    website_url = website_url[:-1]
                
                if website_url is not None:
                    website_url = website_url.split('?', 1)[0]

            except:
                try:
                    DEVELOPMENT = config('DEVELOPMENT', cast=bool)
                except:
                    DEVELOPMENT = False
                
                if DEVELOPMENT == True:
                    try:
                        if website_url.startswith("localhost:"):
                            if 'website_url' in request.query_params:
                                website_url = request.query_params['website_url']
                                if len(website_url) > 1 and website_url[-1] == '/':
                                    website_url = website_url[:-1]
                    except:
                        website_url = "localhost"
                else:
                    return Response("Error during initiating session", status=status.HTTP_400_BAD_REQUEST)

        if 'preview' in request.query_params and request.query_params['preview'] == "true":
            server_url = config('SERVER_URL')
            try:
                sub_server_url = config('SUB_SERVER_URL') + "." + config('SERVER_URL')
            except:
                sub_server_url = server_url
            
            if request.query_params['website_url'].startswith((f"{server_url}", f"{sub_server_url}")):
                website_url = "preview"
                preview = True
            else:
                try:
                    DEVELOPMENT = config('DEVELOPMENT', cast=bool)
                except:
                    DEVELOPMENT = False
                
                if DEVELOPMENT == True:
                    if request.query_params['website_url'].startswith((f"localhost",)):
                        website_url = "preview"
                        preview = True
                    else:
                        return Response("Error during initiating preview session - Reason: Bad URL", status=status.HTTP_400_BAD_REQUEST)
                else:
                    return Response("Error during initiating preview session - Reason: Bad URL", status=status.HTTP_400_BAD_REQUEST)
        else:
            preview = False

        if 'standalone' in request.query_params and request.query_params['standalone'] == "true":
            server_url = config('SERVER_URL')
            try:
                sub_server_url = config('SUB_SERVER_URL') + "." + config('SERVER_URL')
            except:
                sub_server_url = server_url
            
            if request.query_params['website_url'].startswith((f"{server_url}", f"{sub_server_url}")):
                website_url = "standalone page"
                standalone = True
            else:
                try:
                    DEVELOPMENT = config('DEVELOPMENT', cast=bool)
                except:
                    DEVELOPMENT = False
                
                if DEVELOPMENT == True:
                    if request.query_params['website_url'].startswith((f"localhost",)):
                        website_url = "standalone page"
                        standalone = True
                    else:
                        return Response("Error during initiating standalone session - Reason: Bad URL", status=status.HTTP_400_BAD_REQUEST)
                else:
                    return Response("Error during initiating standalone session - Reason: Bad URL", status=status.HTTP_400_BAD_REQUEST)
        else:
            standalone = False

        if preview == True or standalone == True:
            pass
        
        if preview == True:
            session_key = 'bots_preview'
        
        elif standalone == True:
            session_key = 'bots_standalone'
        
        else:
            session_key = 'bots'
        
        if session_key not in request.session:
            request.session[session_key] = dict()
            request.session.modified = True

        if session_bot_id not in request.session[session_key]:
            # Check the room id + session id with any previous sessions
            if request.query_params not in (None, {}) and 'room_id' in request.query_params and 'session_id' in request.query_params:
                try:
                    room_id = uuid.UUID(request.query_params['room_id'])
                except ValueError:
                    return Response("room_id is not of type UUID", status=status.HTTP_400_BAD_REQUEST)

                session_token = request.query_params['session_id']

                if cache.get(f"CLIENTWIDGET_SESSION_TOKEN_{room_id}") is None:
                    qs = ChatSession.objects.filter(session_token=session_token, room_id=room_id)
                    instance = qs.first()
                    if instance is not None:
                        # An archived session. We'll create a new session on the same room
                        print("An archived session. Re-activating the room and deleting the old session")
                        first_visit = False
                        qs.delete()
                        ext = cache.get(room_id)
                        if ext is None:
                            b = Chatbox.objects.get(bot_hash=bot_id)
                            cache.set(f"{room_id}", f"{b.owner.ext_db_label}", timeout=lock_timeout)
                            ext = b.owner.ext_db_label
                        try:
                            reset_chatroom_state(room_id, db_label=ext)
                        except Exception as ex:
                            print(f"Exception during reset_chatroom_state: {ex}")
                        end = cache.get(f"CLIENTWIDGET_SESSION_END_{room_id}", False)
                        if end == True:
                            # Go to INIT
                            print(f"Moving to INIT since previous chat was taken over")
                            cache.delete(f"CLIENTWIDGET_SESSION_END_{room_id}")
                            target_id = None

                        session_token = self.generate_token(bot_id=bot_id, room_id=room_id)
                        instance = ChatSession.objects.create(session_token=session_token, room_id=room_id, ip_address=request.META.get("REMOTE_ADDR"))
                        cache.set(f"CLIENTWIDGET_SESSION_TOKEN_{room_id}", session_token, timeout=lock_timeout)
                            

            if request.query_params in (None, {}) or ('room_id' not in request.query_params) or ('room_id' in request.query_params and cache.get(f"CLIENTWIDGET_SESSION_TOKEN_{request.query_params['room_id']}") is None):
                print("Creating a new room...")
                # We need to create a new room
                bot_obj, variable_json, room_id, _, owner_id = self.get_bot_data(bot_id, user=user, website_url=website_url)
                b = Chatbox.objects.get(bot_hash=bot_id)
                cache.set(f"{room_id}", f"{b.owner.ext_db_label}", timeout=lock_timeout)
                # TODO: Add ChatSession Model
                # Also a new token for this session - We'll use this to validate users for the current session
                session_token = self.generate_token(bot_id=bot_id, room_id=room_id)

                # Store to the Session model
                instance = ChatSession.objects.create(session_token=session_token, room_id=room_id, ip_address=request.META.get("REMOTE_ADDR"))
                
                # Put it into the Cache
                cache.set(f"CLIENTWIDGETTIMEOUT_{str(room_id)}", True)
                cache.set(f"CLIENTWIDGET_SESSION_TOKEN_{str(room_id)}", session_token, timeout=lock_timeout)

                # JSON Serializable format for room_id
                session_room_id = str(room_id)
                variables = get_variables(variable_json)
                if variables is None:
                    variables = dict()
                request.session[session_key][session_bot_id] = {'room_id': session_room_id, 'variables': variables}
                request.session.modified = True
            else:
                # Query Params is not empty. Let's process it
                if 'room_id' in request.query_params:
                    # Try to get the previous chat
                    
                    try:
                        room_id = uuid.UUID(str(request.query_params['room_id']))
                    except ValueError:
                        return Response("room_id is not of type UUID", status=status.HTTP_400_BAD_REQUEST)
                                        
                    if 'targetId' in request.query_params:
                        if first_visit:
                            target_id = request.query_params['targetId']
                        else:
                            # Reset it again since it was an archived chat
                            target_id = None
                    else:
                        target_id = None
                    
                    # TODO: Adding this later for Session Management
                    if 'session_id' not in request.query_params:
                        return Response("Session ID not sent", status=status.HTTP_400_BAD_REQUEST)
                    
                    if first_visit:
                        session_token = request.query_params['session_id']
                    else:
                        # session token already set
                        pass

                    token = cache.get(f"CLIENTWIDGET_SESSION_TOKEN_{str(room_id)}")
                    if token is None:
                        # Session has expired
                        # Renewing the session
                        print(f"For room {room_id}, session has expired. Creating a new room...")
                        
                        session_token = self.renew_token(request=request, bot_id=bot_id, room_id=room_id)
                        
                        cache.set(f"CLIENTWIDGETTIMEOUT_{str(room_id)}", True)
                        cache.set(f"CLIENTWIDGET_SESSION_TOKEN_{str(room_id)}", session_token, timeout=lock_timeout)
                        if session_token is None:
                            return Response(f"Session Expired. No chats for room - {room_id}", status=status.HTTP_404_NOT_FOUND)
                        else:
                            pass
                            #return Response({"session_token" : session_token}, status=status.HTTP_201_CREATED) 
                    
                    elif token == session_token:
                        # Session Key matches
                        pass
                    
                    else:
                        # Mismatch
                        # Check if this is the previous token
                        try:
                            instance = ChatSession.objects.get(room_id=room_id, prev=token)
                            # We need to renew the token
                            session_token = self.renew_token(request=request, bot_id=bot_id, room_id=room_id)
                            if session_token is None:
                                return Response(f"Session Expired. No chats for room - {room_id}", status=status.HTTP_404_NOT_FOUND)
                            else:
                                pass
                        except ChatSession.DoesNotExist:
                            return Response("Invalid Session Key", status=status.HTTP_400_BAD_REQUEST)
                    
                    ext = cache.get(room_id)
                    if ext is None:
                        b = Chatbox.objects.get(bot_hash=bot_id)
                        cache.set(f"{room_id}", f"{b.owner.ext_db_label}", timeout=lock_timeout)
                        ext = b.owner.ext_db_label
                    
                    queryset = ChatRoom.objects.using(ext).filter(room_id=room_id)

                    if queryset.count() == 0:
                        return Response(f"Room ID {room_id} not found", status=status.HTTP_404_NOT_FOUND)
                    
                    instance = queryset.first()
                    request.session[session_key][session_bot_id] = {'room_id': str(room_id), 'variables': instance.variables}

                    # We check the room status when the API call is made. Assumption is that only one client can connect to this room,
                    # so only one such API call can be made per room
                    try:
                        reset_chatroom_state(room_id, db_label=ext)
                    except Exception as ex:
                        print(f"Exception during reset_chatroom_state: {ex}")
                    
                    end = cache.get(f"CLIENTWIDGET_SESSION_END_{room_id}", False)
                    if end == True:
                        # Go to INIT
                        print(f"Moving to INIT since previous chat was taken over")
                        cache.delete(f"CLIENTWIDGET_SESSION_END_{room_id}")
                        target_id = None

                    bot_obj, variable_json, _, _, owner_id = self.get_bot_data(
                        bot_id, bot_com_tid=target_id, user=user,
                        room_id = uuid.UUID(str(room_id)),
                    )
                
                if room_id is not None and cache.get(f"VARIABLES_{room_id}") is None:
                    # Set session variables
                    cache.set(f"VARIABLES_{room_id}", request.session[session_key][session_bot_id]['variables'])
        else:
            # TODO: Potential bugs wrt user and session expiry. Look at this later
            room_id = uuid.UUID(str(request.session[session_key][session_bot_id]['room_id']))
            bot_obj, variable_json, _, _, owner_id = self.get_bot_data(
                bot_id, user=user,
                room_id=room_id,
            )
            
            # TODO: Add ChatSession Model
            # Update the session Timestamp
            token = cache.get(f"CLIENTWIDGET_SESSION_TOKEN_{str(room_id)}")
            if token is None:
                # Token Expired
                session_token = self.renew_token(request=request, bot_id=bot_id, room_id=room_id)
                if session_token is None:
                    return Response(f"Session Expired. No chats for room - {room_id}", status=status.HTTP_404_NOT_FOUND)
                else:
                    pass
                    #return Response({"session_token" : session_token}, status=status.HTTP_201_CREATED)
        
                queryset = ChatSession.objects.filter(room_id=room_id)
                if queryset.count() > 0:
                    queryset.update(updated_on=timezone.now())
                
                # Reset the state
                print(f"Resetting the state")
                ext = cache.get(room_id)
                if ext is None:
                    b = Chatbox.objects.get(bot_hash=bot_id)
                    cache.set(f"{room_id}", f"{b.owner.ext_db_label}", timeout=lock_timeout)
                    ext = b.owner.ext_db_label
                try:
                    reset_chatroom_state(room_id, db_label=ext)
                except Exception as ex:
                    print(f"Exception during reset_chatroom_state: {ex}")
            
            variable_data = get_variables(variable_json)
            session_token = cache.get(f"CLIENTWIDGET_SESSION_TOKEN_{str(room_id)}")

        # TODO: Overrding with session data. Remove this later
        variable_data = request.session[session_key][session_bot_id]['variables']

        if variable_data is not None:
            bot_obj = {**bot_obj, 'variables': variable_data}
            if session_token is not None:
                bot_obj['session_token'] = session_token
            bot_obj['time'] = timezone.now().strftime("%d/%m/%Y %H:%M:%S") # Current time
            bot_obj['owner_id'] = owner_id
            return Response(bot_obj)
        else:
            # No variable data. Keep it empty
            bot_obj = {**bot_obj, 'variables': {}}
            if session_token is not None:
                bot_obj['session_token'] = session_token
            bot_obj['time'] = timezone.now().strftime("%d/%m/%Y %H:%M:%S") # Current time
            bot_obj['owner_id'] = owner_id
            return Response(bot_obj)

    def put(self, request, bot_id: uuid.UUID, format=None):
        """PUT Request Format:
        PUT requests are of the given form:
        {
            "target_id": "b6514efe-c838-4b14-a5ec-65fd30238184",
            "variable": "@name",
            "post_data": "xyz"
        }

        Here, "variable" and "post_data" are optional, and needed only for variable data input.

        Response Format:
        The response will always be of the below format:
        {
            "id": "b6514efe-c838-4b14-a5ec-65fd30238184",
            "icon": "message",
            "message": true,
            "messages": [
                "Thanks @name"
            ],
            "nodeType": "MESSAGE",
            "targetId": "db1beb61-2b5b-4d05-9533-b5906c53d006",
            "variables": {
                "@name": "xyz"
            }
        }

        Args:
            bot_id (uuid.UUID): Represents the bot ID for an existing bot

        Returns:
            HTTP_200_OK: If the proper node is fetched properly, along with the node information
            HTTP_400_BAD_REQUEST: If the client sends PUT before the initial GET request (for setting up the session)
        """
        if 'bots' not in request.session or str(bot_id) not in request.session['bots']:
            return Response("Please send the INIT request for this bot and try again", status.HTTP_400_BAD_REQUEST)
        
        # JSON Serializable format for bot_id
        session_bot_id = str(bot_id)

        if 'variables' not in request.session['bots'][session_bot_id]:
            request.session['bots'][session_bot_id]['variables'] = dict()
            request.session.modified = True
        tid = request.data['target_id']
        owner_id = None
        if 'variable' in request.data:
            if 'post_data' in request.data:
                variable_name = request.data['variable']
                # Store to session
                request.session['bots'][session_bot_id]['variables'][variable_name] = request.data['post_data']
                request.session.modified = True
                bot_obj, var_obj, _, _, owner_id = self.get_bot_data(bot_id, tid)
                # TODO: Overrding with session data. Remove this later
                var_obj = request.session['bots'][session_bot_id]['variables']
                for variable in var_obj:
                    if variable in request.session['bots'][session_bot_id]['variables']:
                        var_obj[variable] = request.session['bots'][session_bot_id]['variables'][variable]
                bot_obj = {**bot_obj, 'variables': var_obj}
                bot_obj['time'] = timezone.now().strftime("%d/%m/%Y %H:%M:%S") # Current time
                bot_obj['owner_id'] = owner_id
                return Response(bot_obj)
            else:
                # Get from session
                if request.data['variable'] in request.session['bots'][session_bot_id]['variables']:
                    bot_obj, var_obj, _, _, owner_id = self.get_bot_data(bot_id, tid)
                    # TODO: Overrding with session data. Remove this later
                    var_obj = request.session['bots'][session_bot_id]['variables']
                    for variable in var_obj:
                        if variable in request.session:
                            var_obj[variable] = request.session['bots'][session_bot_id]['variables'][variable]
                    bot_obj = {**bot_obj, 'variables': var_obj}
                    bot_obj['time'] = timezone.now().strftime("%d/%m/%Y %H:%M:%S") # Current time
                    bot_obj['owner_id'] = owner_id
                    return Response(bot_obj)
                else:
                    return Response(status=status.HTTP_400_BAD_REQUEST)
        else:
            bot_obj, var_obj, _, _, owner_id = self.get_bot_data(bot_id, tid)
        # TODO: Overwriting with session data. Change this later
        bot_obj = {**bot_obj, 'variables': request.session['bots'][session_bot_id]['variables']}
        bot_obj['time'] = timezone.now().strftime("%d/%m/%Y %H:%M:%S") # Current time
        bot_obj['owner_id'] = owner_id
        return Response(bot_obj)


class SendMessageToWebsocket(APIView):
    """API for sending messages to a websocket consumer

    Endpoint URLs:
        api/clientwidget/session/room_id/emit
    """

    def get(self, request, room_id):
        if 'room_id' in request.session and request.session['room_id'] == room_id:
            return Response({'room_id': request.session['room_id']}, status=status.HTTP_200_OK)
        queryset = ChatRoom.objects.using(request.user.ext_db_table).filter(room_id=room_id)
        if queryset.count() > 0:
            room_id = queryset.first().room_id
            return Response({'room_id': room_id}, status=status.HTTP_200_OK)
        return Response("Room ID Not Found", status=status.HTTP_404_NOT_FOUND)

    
    def post(self, request, room_id):
        queryset = ChatRoom.objects.filter(room_id=room_id)
        
        if 'user' in request.data:
            user = request.data['user']
            del request.data['user']
        else:
            return Response("\"user\" parameter must be set in payload", status=status.HTTP_400_BAD_REQUEST)
        
        if 'message' not in request.data:
            return Response("\"message\" parameter must be set in payload", status=status.HTTP_400_BAD_REQUEST)
        else:
            message = request.data['message']
        
        if queryset.count() > 0:
            bot_type = queryset.first().chatbot_type
            if settings.USE_CELERY == True:
                pass
                # _ = send_from_api_task.delay(message, room_id, user)
            else:
                TemplateChatConsumer.send_from_api(message, str(room_id), bot_type, user)
            return Response("Message Sent", status=status.HTTP_200_OK)
        else:
            return Response("Room ID Not Found", status=status.HTTP_404_NOT_FOUND)




class ActiveChatBotListing(APIView):
    """API for Listing all the active Chatbots.

    Endpoints URLS:
        api/clientwidget/listing
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, bot_type=None, sort_date=None):
        """Lists all the active chatbots across all rooms.

        Fetches the bot related data and lists them, for all active bots.
        """
        try:
            if request.user.role not in ('AO'):
                db_label = request.user.ext_db_label
            else:
                # Db label is the owner db_label
                db_label = request.user.created_by.ext_db_label
        except Exception as ex:
            print(f"Error during db_label assignment")
            print(f"{ex}")
            db_label = "default"

        if sort_date is None:
            sort_date = 'desc'
        elif sort_date not in set({'asc', 'desc'}):
            return Response("Sort Parameter must be \"asc\" or \"desc\"", status=status.HTTP_400_BAD_REQUEST)

        if sort_date == 'asc':
            # Ascending order
            field = 'updated_on'
        else:
            # Descending order
            field = '-updated_on'

        if bot_type is None:
            queryset = ChatRoom.objects.using(db_label).filter(bot_is_active=True, admin_id=request.user.id)
        else:
            if bot_type not in ('website', 'whatsapp', 'facebook'):
                return Response("Invalid Bot type", status=status.HTTP_400_BAD_REQUEST)
            queryset = ChatRoom.objects.using(db_label).filter(bot_is_active=True, admin_id=request.user.id)    
        
        # Now sort based on field
        queryset = queryset.order_by(f'{field}')
        serializer = ActiveChatRoomSerializer(queryset, many=True)
        return Response(serializer.data)
    

    def post(self, request, bot_type=None, sort_date=None):
        """POST Request for performing filters for active Chatbots
        """
        try:
            if request.user.role not in ('AO'):
                db_label = request.user.ext_db_label
            else:
                # Db label is the owner db_label
                db_label = request.user.created_by.ext_db_label
        except Exception as ex:
            print(f"Error during db_label assignment")
            print(f"{ex}")
            db_label = "default"

        if sort_date is None:
            sort_date = 'desc'
        elif sort_date not in set({'asc', 'desc'}):
            return Response("Sort Parameter must be \"asc\" or \"desc\"", status=status.HTTP_400_BAD_REQUEST)

        if sort_date == 'asc':
            # Ascending order
            field = 'updated_on'
        else:
            # Descending order
            field = '-updated_on'
        
        # First filter on active bots for current owner
        queryset = ChatRoom.objects.using(db_label).filter(bot_is_active=True, admin_id=request.user.id)
        

        if 'channels' in request.data:
            # Filter by channel
            for channel in request.data['channels']:
                if channel not in ('website', 'whatsapp', 'facebook'):
                    return Response("Invalid Channel type", status=status.HTTP_400_BAD_REQUEST)
            bot_type = request.data['channels']
            print(bot_type)
            queryset = queryset.filter(chatbot_type__in=bot_type)
        
        else:
            if bot_type is None:
                pass
            else:
                for bot in bot_type:
                    if bot not in ('website', 'whatsapp', 'facebook'):
                        return Response("Invalid Bot type", status=status.HTTP_400_BAD_REQUEST)
                queryset = queryset.filter(chatbot_type__in=bot_type)
        

        if 'bot_hash' in request.data:
            # Filter by bot
            bot_hash = []
            for bot in request.data['bot_hash']:
                bot_hash.append(uuid.UUID(bot))
                
            queryset = queryset.filter(bot_id__in=bot_hash)

        if 'operator' in request.data:
            # Filter by operator
            operator_email = request.data['operator']
            active_rooms = ChatRoom.objects.using(db_label).filter(bot_is_active=True).values_list('room_id', flat=True)
            assigned_room = ChatAssign.objects.filter(operators__email__in=operator_email, room_id__in=active_rooms).values_list('room_id', flat=True)
            queryset = queryset.filter(pk__in=assigned_room)

        if 'status' in request.data:
            status_list = request.data['status']
            queryset = queryset.filter(status__in=status_list)

        if 'date_range' in request.data:
            date_range = request.data['date_range']
            if len(date_range) == 1:
                queryset = queryset.filter(created_on=date_range[0])
            else:        
                queryset = queryset.filter(created_on__range=date_range)
        if 'takeover' in request.data:
            queryset = queryset.filter(takeover=True)            

        # Now sort based on field
        queryset = queryset.order_by(f'{field}')
        if 'page' in request.data:
                page = request.data['page']
                gap = 5
                queryset = queryset[gap*int(page)-gap:gap*int(page)]
            
        serializer = ActiveChatRoomSerializer(queryset, many=True)        
        return Response({'data': serializer.data})


class InactiveChatBotListing(APIView):

    permission_classes = [IsAuthenticated]

    def get(self, request):
        
        sort = 'updated_on'
        if 'sort' in self.request.query_params:
            if self.request.query_params['sort'] == 'asc':
                sort = 'updated_on'
        
        queryset = ChatRoom.objects.using(request.user.ext_db_label).filter(admin_id=request.user.id, bot_is_active=False)

        if 'channels' in self.request.query_params:
            channels = self.request.query_params['channels']
            channels = channels.split('|')
            if len(channels) > 0:
                queryset = queryset.filter(chatbot_type__in=channels)
        
        if 'status' in self.request.query_params:
            status = self.request.query_params['status']
            status = status.split('|')
            if len(status) > 0:
                queryset = queryset.filter(status__in=status)
        
        if 'bot' in self.request.query_params:
            bot_id = self.request.query_params['bot']
            print(bot_id)
            bot_id = bot_id.split('|')
            print(bot_id)
            if len(bot_id) > 0:
                queryset = queryset.filter(bot_id__in=bot_id)
        
        if 'date_from' in self.request.query_params and 'date_to' in self.request.query_params:
            date_from = self.request.query_params['date_from']
            date_from = datetime.strptime(date_from, "%Y-%m-%d")
            date_from = date_from - timedelta(minutes=request.user.utc_offset)
            date_to = self.request.query_params['date_to']
            date_to = datetime.strptime(date_to, "%Y-%m-%d")
            date_to = date_to - timedelta(minutes=request.user.utc_offset)
            queryset = queryset.filter(updated_on__gte=date_from, updated_on__lte=date_to+timedelta(days=1))
        queryset = queryset.order_by(F(f'{sort}').desc(nulls_last=True))
        total_length = queryset.count()
        curr_page = 1  
        if 'page' in self.request.query_params:
                page = self.request.query_params['page']
                gap = 10
                queryset = queryset[gap*int(page)-gap:gap*int(page)]
                curr_page = self.request.query_params['page']

        current_length = queryset.count()
        _total_length = float(total_length)
        _current_length = float(current_length)
        try:
            page = _total_length/10
        except Exception:
            page = 0.0

        if page == 0.0:
            page = 1
        else:
            page_int = int(page)
            if (page - page_int) > 0:
                 page = page_int + 1
            else:
                page = page_int
        serializer = ActiveChatRoomSerializer(queryset, many=True)
        return Response({
            'data':serializer.data, 
            'cuurent_length': current_length,
            'total_length': total_length, 
            'current_page': curr_page,
            'total_page': page})   


class DeactivateChatbot(APIView):
    """API for deactivating active chatbots inside a particular room.

    Endpoint URLS:
        api/clientwidget/deactivate/<uuid:room_id>
    """

    def post(self, request, room_id):
        """Sets bot_is_active to False, for all the bots in room_name
        """
        try:
            instance = ChatRoom.objects.using(request.user.ext_db_label).get(room_id=room_id)
            instance.save(bot_is_active=False, using=request.user.ext_db_label, send_update=True)
        except Exception as e:
            print(e)
        return Response(status=status.HTTP_200_OK)


class ChatHistoryDB(APIView):
    """API for dealing with the Chat History from the persistent DB.

    Endpoint URLs:
        1. api/clientwidget/<room_id>/history
        2. api/clientwidget/<room_id>/history/<num_msgs>    
    """
    # TODO: Make this secure
    #permission_classes = [IsAuthenticated]

    def get(self, request, room_id, num_msgs=None):
        """Fetches the LiveChat history for a particular room.

        If num_msgs is None, the whole history will be fetched.
        Otherwise, the last num_msgs will be fetched from the database.

        Returns:
            HTTP_200_OK status code + history content on success, and a HTTP_400_BAD_REQUEST on failure, along with an error message.
        """
        if not request.user.is_authenticated:
            # User not authorized to get the full History
            # We'll first check the lock on this room
            if 'session_id' in request.query_params:
                try:
                    session_id = str(request.query_params['session_id'])
                    queryset = ChatSession.objects.filter(session_token=session_id)
                    if queryset.count() > 0:
                        instance = queryset.first()
                        if instance.room_id != room_id:
                            print(f"Room id does not match")
                            return Response([], status=status.HTTP_200_OK)
                    else:
                        return Response([], status=status.HTTP_200_OK)
                except Exception as ex:
                    print(ex)
                    return Response([], status=status.HTTP_200_OK)
            else:
                return Response([], status=status.HTTP_200_OK)
            
            timeout_status = cache.get(f"CLIENTWIDGET_SESSION_TOKEN_{str(room_id)}")
            if timeout_status is None:
                # Expired
                print("Expired")
                return Response([], status=status.HTTP_200_OK)
            
            if cache.has_key(room_id):
                ext = cache.get(room_id)
            else:
                ext = "default"
        else:
            if request.user.role == 'AM':
                ext = request.user.ext_db_label
            else:
                ext = request.user.operator_of.ext_db_label        

        queryset = ChatRoom.objects.using(ext).filter(room_id=room_id)    
        
        if queryset.count() == 0:
            return Response(f"Room - {room_id} not found in DB", status=status.HTTP_404_NOT_FOUND)
        
        if not request.user.is_authenticated:
            has_error, history = fetch_recent_history_from_db(room_id, num_msgs=num_msgs, db_name=ext)
        else:
            has_error, history = fetch_history_from_db(room_id, num_msgs=num_msgs, db_name=ext)
        
        if has_error == False:
            return Response(history, status=status.HTTP_400_BAD_REQUEST)
        else:
            # Now also fetch the session history
            try:
                session_history = fetch_history_from_redis(room_id, num_msgs)
            except Exception as ex:
                print(ex)
                session_history = []
            
            return Response(history + session_history, status=status.HTTP_200_OK)


    def delete(self, request, room_id, num_msgs=None):
        """Deletes the complete LiveChat history for a particular room.

        This will remove all the messages and variables from the DB.

        Returns:
            HTTP_200_OK status code on success, and a HTTP_400_BAD_REQUEST on failure, along with an error message.
        """
        if not request.user.is_authenticated:
            return Response([], status=status.HTTP_200_OK)
            
        queryset = ChatRoom.objects.using(request.user.ext_db_label).filter(room_id=room_id)        
        if queryset.count() == 0:
            return Response(f"Room - {room_id} not found in DB", status=status.HTTP_404_NOT_FOUND)
        result, error = delete_history_from_db(room_id, num_msgs)
        if result == 1 or result == True:
            return Response(status=status.HTTP_200_OK)
        else:
            return Response(error, status=status.HTTP_400_BAD_REQUEST)


class ChatHistoryRedis(APIView):
    """API for dealing with the Chat History from Redis.

    Endpoint URLs:
        1. api/clientwidget/<room_id>/sessionhistory
        2. api/clientwidget/<room_id>/sessionhistory/<num_msgs>
    """
    #permission_classes = [IsAuthenticated]


    def get(self, request, room_id, num_msgs=None):
        """Fetches the LiveChat history for a particular room.

        If num_msgs is None, the whole history will be fetched.
        Otherwise, the last num_msgs will be fetched from the database.

        Returns:
            HTTP_200_OK status code + history content on success, and a HTTP_404_NOT_FOUND if the room doesn't exist.
        """
        if not request.user.is_authenticated:
            # User not authorized to get the full History
            # We'll first check the lock on this room
            if 'session_id' in request.query_params:
                try:
                    session_id = str(request.query_params['session_id'])
                    queryset = ChatSession.objects.filter(session_token=session_id)
                    if queryset.count() > 0:
                        instance = queryset.first()
                        if instance.room_id != room_id:
                            print(f"Room id does not match")
                            return Response([], status=status.HTTP_200_OK)
                    else:
                        return Response([], status=status.HTTP_200_OK)
                except Exception as ex:
                    print(ex)
                    return Response([], status=status.HTTP_200_OK)
            else:
                return Response([], status=status.HTTP_200_OK)
            
            timeout_status = cache.get(f"CLIENTWIDGET_SESSION_TOKEN_{str(room_id)}")
            if timeout_status is None:
                # Expired
                print("Expired")
                return Response([], status=status.HTTP_200_OK)

            if cache.has_key(room_id):
                ext = cache.get(room_id)
            else:
                ext = 'default'
        else:
            if request.user.role == 'AM':
                ext = request.user.ext_db_label
            else:
                ext = request.user.operator_of.ext_db_label

        queryset = ChatRoom.objects.using(ext).filter(room_id=room_id)        
        
        if queryset.count() == 0:
            return Response(status=status.HTTP_404_NOT_FOUND)
        history = fetch_history_from_redis(room_id, num_msgs)
        return Response(history, status=status.HTTP_200_OK)


    def delete(self, request, room_id, num_msgs=None):
        """Deletes the complete LiveChat history for a particular room.

        If num_msgs is None, the whole history will be deleted.
        Otherwise, the last num_msgs will be deleted from the database.

        Returns:
            HTTP_200_OK status code on success, and a HTTP_400_BAD_REQUEST on failure, or a HTTP_404_NOT_FOUND if the room does not exist.
        """
        if not request.user.is_authenticated:
            return Response([], status=status.HTTP_200_OK)

        queryset = ChatRoom.objects.using(request.user.ext_db_label).filter(room_id=room_id)
        
        if queryset.count() == 0:
            return Response(status=status.HTTP_404_NOT_FOUND)
        result, _ = delete_history_from_redis(room_id, num_msgs)
        if result == 1 or result == True:
            return Response(status=status.HTTP_200_OK)
        else:
            return Response(status=status.HTTP_400_BAD_REQUEST)


class RecentChatHistoryDB(APIView):
    """API for dealing with the Recent Chat History for an existing session id.

    Endpoint URLs:
        1. api/clientwidget/<room_id>/recenthistory
        2. api/clientwidget/<room_id>/recenthistory/<num_msgs>    
    """
    # TODO: Make this secure
    #permission_classes = [IsAuthenticated]

    def get(self, request, room_id, num_msgs=None):
        """Fetches the Recent LiveChat history for a particular room.

        If num_msgs is None, the whole history will be fetched.
        Otherwise, the last num_msgs will be fetched from the database.

        Returns:
            HTTP_200_OK status code + history content on success, and a HTTP_400_BAD_REQUEST on failure, along with an error message.
        """
        if not request.user.is_authenticated:
            # User not authorized to get the full History
            # We'll first check the lock on this room
            if 'session_id' in request.query_params:
                try:
                    session_id = str(request.query_params['session_id'])
                    queryset = ChatSession.objects.filter(session_token=session_id)
                    if queryset.count() > 0:
                        instance = queryset.first()
                        if instance.room_id != room_id:
                            print(f"Room id does not match")
                            return Response([], status=status.HTTP_200_OK)
                    else:
                        return Response([], status=status.HTTP_200_OK)
                except Exception as ex:
                    print(ex)
                    return Response([], status=status.HTTP_200_OK)
            else:
                return Response([], status=status.HTTP_200_OK)
            
            timeout_status = cache.get(f"CLIENTWIDGET_SESSION_TOKEN_{str(room_id)}")
            if timeout_status is None:
                # Expired
                print("Expired")
                return Response([], status=status.HTTP_200_OK)

        queryset = ChatRoom.objects.using(request.user.ext_db_label).filter(room_id=room_id)
        
        if queryset.count() == 0:
            return Response(f"Room - {room_id} not found in DB", status=status.HTTP_404_NOT_FOUND)
        has_error, history = fetch_recent_history_from_db(room_id, num_msgs=num_msgs)
        if has_error == False:
            return Response(history, status=status.HTTP_400_BAD_REQUEST)
        else:
            return Response(history, status=status.HTTP_200_OK)
    

    def post(self, request, room_id, num_msgs=None):

        if not request.user.is_authenticated:
            if 'session_id' in request.query_params:
                try:
                    session_id = str(request.query_params['session_id'])
                    queryset = ChatSession.objects.filter(session_token=session_id, room_id=room_id)
                    if queryset.count() > 0:
                        pass
                    else:
                        return Response([], status=status.HTTP_200_OK)
                except Exception as ex:
                    print(ex)
                    return Response([], status=status.HTTP_200_OK)
            else:
                return Response("Please ensure that you contact our developers regarding using our API", status=status.HTTP_401_UNAUTHORIZED)

            if cache.has_key(room_id):
                ext = cache.get(room_id)
            else:
                ext = 'default'
        else:
            if request.user.role == 'AM':
                ext = request.user.ext_db_label
            else:
                ext = request.user.operator_of.ext_db_label
        
        instance = ChatRoom.objects.using(ext).filter(room_id=room_id).first()
        
        if not instance:
            return Response(f"Room - {room_id} not found in DB", status=status.HTTP_404_NOT_FOUND)
        
        instance.recent_messages = []
        instance.save(using=ext)
        
        return Response("Updated", status=status.HTTP_200_OK)


class FlushSessiontoDB(APIView):
    """API for flushing any existing session content into the Database
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, room_id, reset=None):
        """Dumps the session data into the DB
        """
        if reset == 0:
            reset = False
        else:
            reset = True if reset is not None else False
        cleanup_room_redis(room_id, reset_count=reset)
        return Response(status=status.HTTP_200_OK)


class FetchVariablesRedis(APIView):
    """API for fetching the currently updated variable data for the current session
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, room_id):
        """Gets the variables under `room_id` for the current session.

        Returns:
            Status Code: 200 on success.
            Status Code: 404 if there are no existing sessions for `room_id`.
        """
        if request.query_params not in (None, {}):
            if 'override' in request.query_params and request.query_params['override'] == 'true':
                override = True
            else:
                override = False
        else:
            override = False
        
        if request.user.role == 'AM':
            ext = request.user.ext_db_label
        else:
            ext = request.user.operator_of.ext_db_label        

        chatroom = ChatRoom.objects.using(ext).filter(room_id=room_id).first()
        if chatroom is None:
            return Response("Bot is not found", status=status.HTTP_404_NOT_FOUND)
        
        bot_id = chatroom.bot_id

        chatbox = Chatbox.objects.filter(bot_hash=bot_id).first()
        if chatbox is None:
            return Response("Bot not found in chatbox", status=status.HTTP_404_NOT_FOUND)
        
        bot_name = chatbox.title

        err, content = fetch_variables_from_redis(room_id, override=override, bot_type=chatbox.chatbot_type)
        
        lead_variables = chatbox.bot_lead_json
        
        # Filter on only lead variables
        for key, value in content.items():
            if key in lead_variables:
                lead_variables[key] = value

        if err:
            if chatbox.chatbot_type == 'website':
                utm_code_serializer = serializers.UTMCodeSerializerGetter(chatroom)
                return Response({
                    'content': lead_variables,
                    'bot_name': bot_name,
                    'utm': utm_code_serializer.data,
                    'channel_id': chatroom.channel_id,
                    'webiste_url': chatroom.website_url,
                }, status=status.HTTP_200_OK)
            else:
                return Response({
                    'content': lead_variables,
                    'bot_name': bot_name,
                    'channel_id': chatroom.channel_id,
                    'webiste_url': chatroom.website_url,
                }, status=status.HTTP_200_OK)   
        else:
            return Response(content, status=status.HTTP_404_NOT_FOUND)


class FetchVariablesDB(APIView):
    """API for fetching the variable data for a particular room from the DB
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, room_id):
        """Gets the variables under `room_id` from the DB.

        Returns:
            Status Code: 200 on success.
            Status Code: 404 if `room_id` is not found in DB.
        """

        if request.user.role == 'AM':
            ext = request.user.ext_db_label
        else:
            ext = request.user.operator_of.ext_db_label        

        chatroom = ChatRoom.objects.using(ext).filter(room_id=room_id).first()
        if chatroom is None:
            return Response("Bot is not found", status=status.HTTP_404_NOT_FOUND)
        
        bot_id = chatroom.bot_id

        chatbox = Chatbox.objects.filter(bot_hash=bot_id).first()
        if chatbox is None:
            return Response("Bot not found in chatbox", status=status.HTTP_404_NOT_FOUND)
        
        bot_name = chatbox.title

        err, content = fetch_variables_from_db(room_id, db_name=request.user.ext_db_label)

        lead_variables = chatbox.bot_lead_json
        
        # Filter on only lead variables
        for key, value in content.items():
            if key in lead_variables:
                lead_variables[key] = value

        if err:
            chat_review = ChatReview.objects.filter(room_id=room_id, active=True)
            serializer = ChatReviewListingAPISerializer(chat_review, many=True)
            if chatbox.chatbot_type == 'website':
                utm_code_serializer = serializers.UTMCodeSerializerGetter(chatroom)
                return Response({
                    'content': lead_variables,
                    'chat_review': serializer.data,
                    'bot_name': bot_name,
                    'utm': utm_code_serializer.data,
                    'channel_id': chatroom.channel_id,
                    'webiste_url': chatroom.website_url
                }, status=status.HTTP_200_OK)
            else:
                return Response({
                    'content': lead_variables,
                    'chat_review': serializer.data,
                    'bot_name': bot_name,
                    'channel_id': chatroom.channel_id,
                    'webiste_url': chatroom.website_url,
                }, status=status.HTTP_200_OK)
        else:
            return Response(content, status=status.HTTP_404_NOT_FOUND)


class SendEmailtoAdmins(APIView):

    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            from apps.taskscheduler.schedule_manager.clientwidget_jobs import \
                ClientWidgetJobs
            ClientWidgetJobs.clientwidget_send_email()
            return Response("Sent Emails to all subscribed admins", status=status.HTTP_200_OK)
        except:
            return Response("Error during sending email", status=status.HTTP_404_NOT_FOUND)


class IPTest(APIView):
    def get(self, request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return Response(f"Your IP Address is {ip}", status=status.HTTP_200_OK)


class UTMCodeAPI(generics.GenericAPIView):

    serializer_class = serializers.UTMCodeSerializer

    def post(self, request, room_id):
        try:
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            bot_id = serializer.data['bot_id']
            chatbox = Chatbox.objects.get(pk=uuid.UUID(bot_id))
            db_label = chatbox.owner.ext_db_label
            chatroom = ChatRoom.objects.using(db_label).get(room_id=room_id)
            chatroom.utm_source = serializer.data['utm_source']
            chatroom.utm_medium = serializer.data['utm_medium']
            chatroom.utm_campaign = serializer.data['utm_campaign']
            chatroom.utm_term = serializer.data['utm_term']
            chatroom.utm_content = serializer.data['utm_content']
            chatroom.website_url = serializer.data['website_url']
            chatroom.save(using=db_label)
            return Response({'status': 'UTMCode Added'}, status=status.HTTP_200_OK)
        except Chatbox.DoesNotExist as e:
            print(e)
            return Response({'status': 'Chatbox does not exists'}, status=status.HTTP_404_NOT_FOUND)
        except ChatRoom.DoesNotExist as e:
            print(e)
            return Response({'status': 'Chatroom does not exists'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            print(e)
            return Response({'status': 'Something went wrong.'}, status=status.HTTP_400_BAD_REQUEST)            


class MakeChatRoomsInactive(APIView):

    def get(self, request, owner_id, room_id):
        
        try:
            time.sleep(5)
            user = User.objects.get(uuid=owner_id)
            chatroom = ChatRoom.objects.using(user.ext_db_label).get(pk=room_id)
            return Response({'status': 'Room Already Flushed'})
        except Exception as e:
            print(e)
            return Response({'status': 'Something went wrong'}, status=status.HTTP_400_BAD_REQUEST)


class TestingAPI(APIView):

    def get(self, request, response_type=None):
        query_params = request.query_params
        if response_type is None:
            data = {i: str(query_params[i]) + " updated" for i in query_params}
            data = {
                **data,
                'status': True,
            }
        elif response_type == 'list':
            data = [{i: str(query_params[i]) + " updated"} for i in query_params]
        return Response(data, status=status.HTTP_200_OK)
    

    def post(self, request, response_type=None):
        payload = request.data
        if response_type is None:
            data = {i: str(payload[i]) + " updated" for i in payload}
            data = {
                **data,
                'status': True,
            }
        elif response_type == 'list':
            data = [{i: str(payload[i]) + " updated"} for i in payload]
        return Response(data, status=status.HTTP_200_OK)
