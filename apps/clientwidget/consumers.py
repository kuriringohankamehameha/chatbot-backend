import _thread
import json
import os
import time
import urllib.parse
import uuid
from datetime import datetime
import requests
from asgiref.sync import async_to_sync, sync_to_async
from celery import task, shared_task
from channels.generic.websocket import WebsocketConsumer
from channels.layers import get_channel_layer
from decouple import UndefinedValueError, config
from django.apps import apps
from django.conf import settings
from django.core.cache import cache
from django.core.mail import EmailMessage, get_connection, send_mail
from django.db import transaction
from django.db.models import Count
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.encoding import force_bytes, force_text
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from apps.accounts.models import Teams, User
from apps.clientwidget.models import ChatRoom

from . import events, tasks
from .exceptions import LiveChatException, log_consumer_exceptions, logger
from .serializers import ActiveChatRoomSerializer
from .views import BUFFER_TIME, lock_timeout, server_addr, shared_client

Chatbox = apps.get_model(app_label='chatbox', model_name='Chatbox')
  

def chat_lead_send_update(room_id, is_lead, data):
    """Sends an Email Update if a lead is encountered during an ongoing live-chat
    """
    ext = cache.get(room_id)
    queryset = ChatRoom.objects.using(ext).filter(pk=room_id, bot_is_active=True)
    if queryset.count() == 0:
        return
    
    chatroom = queryset.first()

    from_email = config('EMAIL_HOST_USER')
    
    owner = User.objects.get(id=chatroom.admin_id)
    if owner is None:
        return
    
    to_email = [owner.email]

    if data is None:
        # Possibly need to fetch from DB
        data = chatroom.variables
    
    if is_lead == True:
        if cache.get(f'CLIENTWIDGETROOMLOCK_{room_id}') is not None:
            # Ongoing chat. Send Email
            messages = events.fetch_history_from_redis(room_id)
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
            messages = events.fetch_history_from_redis(room_id)
            message = render_to_string('clientwidget/send_nonlead_encounter_email.html', {'user': owner, 'nonlead_data': data, 'messages': messages})

            logger.info(f"Non-Lead Encountered. Sending an Email to owner {owner.email}")
            mail_subject = "Clientwidget Anonymous User Encountered"
            send_mail(mail_subject, message, from_email, to_email, fail_silently=True, html_message=message)
        else:
            # Chat has completed
            pass


def send_to_operator(room_id, owner_id, channel_layer, data):
    try:
        # Send to operator group
        client_map = cache.get(f"CLIENT_MAP_{owner_id}")
        print(f"CLIENT MAP = {client_map}")
        logger.info(f"CLIENT MAP = {client_map}")

        #TODO: NEED TO ADD CELERY TASK HERE.
        if client_map is not None:
            operator_id = client_map.get(str(room_id))
            for operator in operator_id:
                async_to_sync(channel_layer.group_send)(
                    operator,
                    {
                        **data,
                        'type': 'chat_message',
                    }

                )
    except Exception as ex:
        print(ex)


@log_consumer_exceptions
class LongPollingConsumer(WebsocketConsumer):
    """Long Polling Consumer for fetching the Listing details from Chat Management
    
    This consumer will always receive packets of this format:
    {
        "bot_hash": ["ae315675-36ed-4db6-b056-78ce3f116531"],
        "channels": ["whatsapp"],
        "statuses": ["pending"],
        "date_range": ["2020-10-06", "2020-10-10"],
        "page": 1
    }

    Raises:
        LiveChatException: On Payload Format Error
    """

    def connect(self):
        if 'owner_id' in self.scope['url_route']['kwargs']:
            self.owner_id = self.scope['url_route']['kwargs']['owner_id']
        else:
            self.disconnect(400)
                
        self.room_group_name = 'listing_channel_%s' % str(self.owner_id)
        print('LongPolling Listing............')
        print(f"Group Name: {self.room_group_name}")
        self.accept()
        self.user = User.objects.get(uuid=self.owner_id)
        self.admin_id = self.user.uuid
        if self.user.role == 'AO':
            self.admin_id = self.user.operator_of.uuid
            try:
                _team_name = self.user.team_member.name
                _team_name = _team_name.replace(" ", "")
                self.team_name = 'team_{}_{}'.format(self.user.operator_of.uuid, _team_name) 
                async_to_sync(self.channel_layer.group_add)(
                    self.team_name,
                    self.channel_name
                )
            except Exception as e:
                print(e)    
   
        
        async_to_sync(self.channel_layer.group_add)(
            self.room_group_name,
            self.channel_name
        )     
        print(f"Polling Consumer now added to group {self.room_group_name}")

    def disconnect(self, close_code):
        print(f"Disconnecting with close code = {close_code}")

        try:
            async_to_sync(self.channel_layer.group_discard)(
                self.room_group_name,
                self.channel_name
            )
        except Exception as ex:
            print(ex)

    def receive(self, text_data):
        
        async_to_sync(self.channel_layer.group_send)(
            self.room_group_name,
            {
                'type': 'bot_listing',
                'payload': response,
            }
        )

    def bot_listing(self, event):
        if 'payload' in event:
            payload = event['payload']
            self.send(text_data=json.dumps(payload))
    
    def listing_channel_event(self, event):
        if 'payload' in event:
            self.send(text_data=json.dumps(event['payload']))
        else:
            self.send(text_data=json.dumps(event))

    def get_user(self, user_uuid):
        user = User.objects.get(uuid=user_uuid)
        return user        


@log_consumer_exceptions
class ClientWidgetConsumer(WebsocketConsumer):
    """Websocket Consumer for the ClientWidget
    """

    def get_group_name(self):
        pass


    def end_chat(self, bot_obj):
        self.session_end = True
        self.exclude_count = True
        if hasattr(self, 'room_id') and self.room_id is not None:
            ext = cache.get(str(self.room_id))
            queryset = ChatRoom.objects.using(bot_obj.owner.ext_db_label).filter(pk=self.room_id)
            if queryset.count() == 0:
                logger.info('no_chatroom')
                logger.info(f"{ext}")
                pass
            else:
                logger.info(f"<<----END CHAT--->>")
                instance = queryset.first()
                instance.end_chat = True
                instance.save(using=bot_obj.owner.ext_db_label, send_update=True)


    def get_bot_data(self, bot_id, bot_com_tid=None, user=None, room_id=None, room_name=None):
        """This method fetches the bot specific data from the `Chatbox` model.

        Note:
            We are returning a generated `room_id` and `room_name` in case we need to create a new room for the bot.
            In this case, the input arguments `room_id` and `room_name` must be both None 
        
        :
            bot_id: The id of the relevant bot.
            bot_com_tid: The target_id node we need to extract information from. This must be None for generating the first INIT response.
            user: The user object from the USER model. This is None for any anonymous user
            room_id: The UUID room identification object for the current room, it it is already created.
            room_name: The room name for the current room, if it is already created.

        Returns:
            A tuple (bot_data_json, bot_variable_json, room_id, room_name) if successful, a tuple of (None, None, None, None) otherwise.
        """
        try:
            bot_obj = Chatbox.objects.get(pk=bot_id)
            if bot_com_tid:
                for key_id in bot_obj.bot_data_json:
                    if key_id == bot_com_tid:
                        bot_component_response = bot_obj.bot_data_json[key_id]
                        var_response = bot_obj.bot_variable_json

                        # New Changes
                        end = cache.get(f"CLIENTWIDGET_SESSION_END_{room_id}", False)
                        if end == True:
                            # Go to INIT
                            logger.info(f"Moving to INIT since previous chat was taken over")
                            return self.get_bot_data(bot_id, bot_com_tid=None, user='AnonymousUser', room_id=self.room_id, room_name=room_name)

                        if 'nodeType' in bot_component_response and bot_component_response['nodeType'] == 'INIT':
                            self.exclude_count = True

                        if 'nodeType' in bot_component_response and bot_component_response['nodeType'] == 'END':
                            # End of Session
                            self.session_end = True
                            self.exclude_count = True
                            if hasattr(self, 'room_id') and self.room_id is not None:
                                ext = cache.get(str(room_id))
                                queryset = ChatRoom.objects.using(bot_obj.owner.ext_db_label).filter(pk=self.room_id)
                                if queryset.count() == 0:
                                    logger.info('no_chatroom')
                                    logger.info(f"{ext}")
                                    pass
                                else:
                                    logger.info(f"<<----END CHAT--->>")
                                    instance = queryset.first()
                                    instance.end_chat = True
                                    instance.save(using=bot_obj.owner.ext_db_label, send_update=True)
                        
                        elif 'nodeType' in bot_component_response and bot_component_response['nodeType'] == 'SET_VARIABLE':
                            try:
                                variable_list = bot_component_response.get('variableList', [])

                                for variable_node in variable_list:
                                    variable = variable_node['variable']
                                    value = variable_node.get('value', '')

                                    events.set_session_variable(self.room_id, variable, value, bot_type="website")
                                    status = self.check_if_lead(variable, value)
                                    if status:
                                        # Set the flag
                                        cache.set(f"IS_LEAD_{self.room_name}", True, timeout=lock_timeout + BUFFER_TIME)
                                
                                target_id = bot_component_response.get('targetId')
                                
                                if target_id not in ['', None, 'END']:
                                    return self.get_bot_data(bot_id, bot_com_tid=target_id)
                                else:
                                    self.end_chat(bot_obj)
                                    return None, None, None, None
                            
                            except Exception as ex:
                                logger.critical(f"Exception during SET_VARIABLE component: {ex}")
                        
                        elif 'nodeType' in bot_component_response and bot_component_response['nodeType'] == 'GOAL':
                            try:
                                variable = bot_component_response['variable']
                                value = bot_component_response.get('value', 'true')
                                target_id = bot_component_response.get('targetId')

                                events.set_session_variable(self.room_id, variable, value, bot_type="website")
                                status = self.check_if_lead(variable, value)
                                if status:
                                    # Set the flag
                                    cache.set(f"IS_LEAD_{self.room_name}", True, timeout=lock_timeout + BUFFER_TIME)
                                
                                if target_id not in [None, '', 'END']:
                                    return self.get_bot_data(bot_id, bot_com_tid=target_id)
                                else:
                                    self.end_chat(bot_obj)
                                    return None, None, None, None
                            except Exception as ex:
                                 logger.critical(f"Exception during GOAL component: {ex}")
                        
                        elif 'nodeType' in bot_component_response and bot_component_response['nodeType'] == 'SET_VARIABLE_BETA':
                            try:
                                target_id, variable, value = events.parse_set_variable_expression(self.room_id, bot_id, bot_component_response, bot_obj.owner_id, bot_type='website')
                                status = self.check_if_lead(variable, value)
                                if status:
                                    # Set the flag
                                    cache.set(f"IS_LEAD_{self.room_name}", True, timeout=lock_timeout + BUFFER_TIME)
                                
                                if target_id not in [None, '', 'END']:
                                    return self.get_bot_data(bot_id, bot_com_tid=target_id)
                                else:
                                    self.end_chat(bot_obj)
                                    return None, None, None, None
                            
                            except Exception as ex:
                                logger.critical(f"Exception during SET_VARIABLE_BETA component: {ex}")
                        
                        elif 'nodeType' in bot_component_response and bot_component_response['nodeType'] == 'WEBHOOK':
                            try:
                                target_id, _ = events.process_webhook_node(self.room_id, bot_id, bot_component_response, bot_obj.owner_id)
                                if target_id not in [None, '', 'END']:
                                    return self.get_bot_data(bot_id, bot_com_tid=target_id)
                                else:
                                    self.end_chat(bot_obj)
                                    return None, None, None, None
                            except Exception as ex:
                                logger.critical(f"Exception during WEBHOOK component: {ex}")

                        # Now check if the node is of type: AGENT_TRANSFER
                        elif 'nodeType' in bot_component_response and bot_component_response['nodeType'] in ['AGENT_TRANSFER', 'TEAM_TRANSFER']:
                            # End of Session after livechat
                            self.session_end = True

                            # Set the takeover field to be True
                            if hasattr(self, 'room_id') and self.room_id is not None:
                                ext = cache.get(str(room_id))
                                queryset = ChatRoom.objects.using(bot_obj.owner.ext_db_label).filter(pk=self.room_id)
                                if queryset.count() == 0:
                                    logger.info('no_chatroom')
                                    logger.info(f"{ext}")
                                    pass
                                else:
                                    instance = queryset.first()
                                    instance.takeover = True
                                    instance.save(using=ext, send_update=True)
                                    
                                    if hasattr(self, 'is_subscribed') and self.is_subscribed == True:
                                        if hasattr(self, 'is_lead') and self.is_lead == False:
                                            # Not a Lead
                                            try:
                                                nonlead_data = cache.get(f"VARIABLES_{self.room_name}")
                                                _thread.start_new_thread(chat_lead_send_update, (self.room_id, False, nonlead_data))
                                            except Exception as ex:
                                                print(ex)
                                                pass
                                        else:
                                            # Send email to Admin
                                            try:
                                                lead_data = cache.get(f"VARIABLES_{self.room_name}")
                                                lead_fields = cache.get(f"CLIENTWIDGETLEADDATA_{self.room_name}")
                                                if lead_fields is not None and lead_data is not None:
                                                    lead_data = {key: value for key, value in lead_data.items() if key in lead_fields}
                                                _thread.start_new_thread(chat_lead_send_update, (self.room_id, True, lead_data))
                                            except Exception as ex:
                                                print(ex)
                                                pass
                        if bot_com_tid in ['', 'END']:
                            logger.info(f"TargetID is empty. Exiting the chat...")
                            self.end_chat(bot_obj)
                            return None, None, None, None
                        
                        return bot_component_response, var_response, None, None
                
                if bot_com_tid in ['', 'END']:
                    logger.info(f"TargetID is empty. Exiting the chat...")
                    self.end_chat(bot_obj)
                    return None, None, None, None
                
                return None, None, None, None
            else:
                for key_id in bot_obj.bot_data_json:
                    if bot_obj.bot_data_json[key_id]['nodeType'] == 'INIT':
                        bot_component_response = bot_obj.bot_data_json[key_id]
                        self.exclude_count = True
                        if room_id is None:
                            bot_component_response['room_id'], bot_component_response['room_name'] = events.create_room(user, content={
                                'room_name': '',
                                'bot_id': str(bot_obj.bot_hash),
                                'bot_is_active': True,
                                'num_msgs': 0,
                            }, bot_id=bot_obj.bot_hash)
                        else:
                            bot_component_response['room_id'], bot_component_response['room_name'] = room_id, room_name
                            # Make it active again
                            ext = cache.get(str(room_id))
                            queryset = ChatRoom.objects.using(ext).filter(room_id=room_id)
                            instance = queryset.first()
                            instance.bot_is_active = True
                            instance.save(using=ext, send_update=True)
                        return bot_component_response, bot_obj.bot_variable_json, bot_component_response['room_id'], bot_component_response['room_name']
                return None, None, None, None
        except Chatbox.DoesNotExist:
            return None, None, None, None


    def check_if_lead(self, variable, value) -> bool:
        """Checks if the anonymous user matches a lead. This first pops the variable from the lead filters, if it exists
        """
        if hasattr(self, 'lead_fields'):
            if self.lead_fields is None:
                return False
            if variable in self.lead_fields and value not in (None, ""):
                self.lead_fields = set() # New filter -> Match if atleast one lead field is non empty
                cache.set(f"CLIENTWIDGETLEADFIELDS_{self.room_name}", list(self.lead_fields), timeout=lock_timeout + BUFFER_TIME)
            if self.lead_fields == set():
                self.is_lead = True
                return True
            else:
                return False
        else:
            return False


    def connect(self):
        """Handler method when a connection is established with the LiveChat websocket.

        This is responsible for setting up the session information.
        We store some session related data in the form of session['variables'] for storing variable information.
        We also increment the number of users on that particular room.
        """
        if 'room_id' in self.scope['url_route']['kwargs']:
            self.room_name = str(self.scope['url_route']['kwargs']['room_id'])
        else:
            # Admin does not have a room name
            self.room_name = None
        
        query_params = self.scope['query_string'].decode('utf-8')

        logger.info(f"Query Params: {query_params}")

        if query_params.startswith("preview=true&bot_id="):
            self.preview = True
            self.standalone = False
            self.bot_id = query_params[20:]
            try:
                self.bot_id = uuid.UUID(self.bot_id)
            except:
                self.room_id = None
                self.disconnect(400)
        elif query_params.startswith("standalone=true&bot_id="):
            self.preview = False
            self.standalone = True
            self.bot_id = query_params[20:]
            try:
                self.bot_id = uuid.UUID(self.bot_id)
            except:
                self.room_id = None
                self.disconnect(400)
        else:
            self.preview = False
            self.standalone = False
            self.bot_id = None

        if 'owner_id' in self.scope['url_route']['kwargs']:
            self.owner_id = str(self.scope['url_route']['kwargs']['owner_id'])
        else:
            self.owner_id = None

        self.sender_group_name = str(self.owner_id)

        self.room_group_name = self.room_name if self.room_name is not None else self.sender_group_name
        
        if self.room_name is not None:
            self.receiver_group_name = str(self.room_name)
        else:
            self.receiver_group_name = str(self.sender_group_name)
        
        logger.info(f"Sender Group name is {self.sender_group_name}, and Receiver Group Name is {self.receiver_group_name}")

        # Join room group
        # Now there are two channels - One for sending and one for receiving

        # While each client has it's own independent receiver group
        self.room_group_name = self.receiver_group_name
        async_to_sync(self.channel_layer.group_add)(
            self.room_group_name,
            self.channel_name
        )
        print(f"Client now added to group {self.room_group_name}")

        print(f"group name = {self.room_group_name}")
        logger.info(f"group name = {self.room_group_name}")

        self.user = str(self.scope['user'])
        print(f'user is {self.user}')
        logger.info(f'user is {self.user}')
        
        self.accept()
        room_name = self.room_name
        try:
            self.room_id = uuid.UUID(self.room_name)
        except (ValueError, TypeError, ):
            self.room_id = None
        
        if self.room_id is None:
            return
        
        self.exclude_count = False

        # Get the room lock
        lock = cache.get(f'CLIENTWIDGETROOMLOCK_{self.room_name}')
        if lock == True:
            # Someone's there. Don't hit the DB
            room_information = cache.get(f'CLIENTWIDGETROOMINFO_{self.room_name}')
            
            # Get the lead information from cache
            self.lead_fields = cache.get(f"CLIENTWIDGETLEADFIELDS_{room_name}")
            if self.lead_fields is None:
                pass
            elif isinstance(self.lead_fields, list):
                self.lead_fields = set(self.lead_fields)
            
            # Get the subscription information
            self.is_subscribed = cache.get(f"CLIENTWIDGETSUBSCRIBED_{room_name}")
            if self.is_subscribed is None:
                self.is_subscribed = False

            if room_information is None:
                # TODO: Change this later
                ext = cache.get(str(self.room_id))
                try:
                    if self.room_id is None:
                        
                        instance = ChatRoom.objects.using(ext).get(room_name=room_name)
                    else:
                        instance = ChatRoom.objects.using(ext).get(room_id=self.room_id)
                    self.room_id, self.chatbot_type = instance.room_id, instance.chatbot_type
                except ChatRoom.DoesNotExist:
                    self.room_id = None
                    self.disconnect(400)
            else:
                self.room_id, self.chatbot_type = room_information
            
            # Session End Flag
            user = self.scope['user']
            if hasattr(user, 'role') and user.role in ('AM', 'AO'):
                # Set it to True
                cache.set(f"CLIENTWIDGET_SESSION_END_{self.room_name}", True, timeout=lock_timeout + BUFFER_TIME)
                self.session_end = True
        else:
            # Hit the DB
            self.is_subscribed = False
            with transaction.atomic():
                try:
                    ext = cache.get(self.room_id)
                    logger.info(f'{ext}--->')
                    instance = ChatRoom.objects.using(ext).get(room_id=self.room_id)
                except ChatRoom.DoesNotExist as e:
                    logger.info(f'{e}')
                    instance = None
                
                if instance is not None:
                    try:
                        self.bot_id = instance.bot_id
                        if self.bot_id is not None:
                            chatbox_instance = Chatbox.objects.get(pk=self.bot_id)
                        else:
                            chatbox_instance = None
                    except Chatbox.DoesNotExist:
                        chatbox_instance = None
            
            if hasattr(instance, 'num_msgs'):
                # Initialize the Counter
                num_msgs = instance.num_msgs
                cache.set(f"CLIENTWIDGET_COUNT_{self.room_name}", num_msgs, timeout=lock_timeout + BUFFER_TIME)

            # Start our expiry timer (this is the oldest key for this room)
            cache.set(f"CLIENTWIDGET_EXPIRY_LOCK_{self.room_name}", True, timeout=lock_timeout)
            
            if instance is not None and chatbox_instance is not None:
                self.lead_fields = chatbox_instance.bot_lead_json

                if hasattr(chatbox_instance, 'subscription_type') and chatbox_instance.subscription_type in ('email', 'all',):
                    self.is_subscribed = True
                
                lead_fields = cache.get(f"CLIENTWIDGETLEADFIELDS_{room_name}")
                if lead_fields is None:
                    # Fresh Session
                    if self.lead_fields is not None:
                        self.lead_fields = list(self.lead_fields.keys())
                        if len(self.lead_fields) == 0:
                            self.lead_fields = None
                        else:
                            self.lead_fields = set(self.lead_fields)
                    else:
                        self.lead_fields = None
                    
                    if self.lead_fields is not None:
                        cache.set(f"CLIENTWIDGETLEADFIELDS_{room_name}", list(self.lead_fields), timeout=lock_timeout + BUFFER_TIME)
                        cache.set(f"CLIENTWIDGETLEADDATA_{room_name}", {key: "" for key in list(self.lead_fields)}, timeout=lock_timeout + BUFFER_TIME)
                        # Subscribe only if there are lead fields available
                        cache.set(f"CLIENTWIDGETSUBSCRIBED_{room_name}", self.is_subscribed, timeout=lock_timeout + BUFFER_TIME)
                else:
                    # Existing Session
                    self.lead_fields = set(lead_fields) if isinstance(lead_fields, list) else None
                    if hasattr(chatbox_instance, 'subscription_type') and chatbox_instance.subscription_type in ('email', 'all',):
                        self.is_subscribed = True
            else:
                self.lead_fields = None

            if instance is not None:
                self.room_id = instance.room_id
                try:
                    chatbot = Chatbox.objects.get(pk=instance.bot_id)
                    self.chatbot_type = chatbot.chatbot_type
                    self.bot_id = chatbot.pk
                except Exception as e:
                    print(e)
                    self.bot_id = None

            else:
                # NOTE: This shouldn't happen through normal means
                self.room_id, _ = events.create_room(self.user, content={
                    'room_name': self.room_name,
                    'num_msgs': 0,
                }, bot_id=self.bot_id, preview=self.preview, standalone=self.standalone)
                self.chatbot_type = 'website' # Default value
                if self.room_id is None:
                    logger.critical(f"Error while creating room")
                    self.disconnect(400)
                
                logger.warning(f"LiveChat room created for {self.room_name}. You're probably using the demo app")
                logger.newline()
            
            # Set the room information on the cache
            cache.set(f'CLIENTWIDGETROOMINFO_{self.room_name}', tuple((str(self.room_id), self.chatbot_type)), timeout=lock_timeout + BUFFER_TIME)

        self.num_msgs = events.get_msgcount(self.room_name)

        self.num_users = events.increment_usercount(self.room_name)
        print(f"Now group has {self.num_users} members")
        logger.info(f"Now group has {self.num_users} members")

        # Set the room lock
        cache.set(f'CLIENTWIDGETROOMLOCK_{self.room_name}', True, timeout=lock_timeout + BUFFER_TIME)

        # This must be atomic
        if self.num_users == 1 and self.chatbot_type == 'website':
            ext = cache.get(self.room_id)
            if self.room_id is None:
                queryset = ChatRoom.objects.filter(room_name=self.room_name)
            else:
                queryset = ChatRoom.objects.using(ext).filter(room_id=self.room_id)
            if queryset.count() > 0:
                if self.chatbot_type == 'website':
                    instance = queryset.first()
                    _modified = False

                    if hasattr(instance, 'updated_on') and instance.updated_on is None:
                        instance.updated_on = instance.created_on
                    _modified = True
                    
                    if hasattr(instance, 'end_time') and instance.end_time is not None:
                        _modified = True
                        instance.end_time = None
                    
                    if instance.bot_is_active == False:
                        _modified = True
                        instance.bot_is_active = True
                    
                    if _modified == True:
                        instance.save(send_update=True, using=ext)
            
            variables = cache.get(f"VARIABLES_{self.room_name}")
            if variables is None:
                # Get the variables from the DB, if the room exists already
                if queryset.count() == 0:
                    cache.set(f"VARIABLES_{self.room_name}", dict(), timeout=lock_timeout + BUFFER_TIME)
                else:
                    # Fetch from DB
                    cache.set(f"VARIABLES_{self.room_name}", instance.variables, timeout=lock_timeout + BUFFER_TIME)

        else:
            # Get it from the cache. Somebody's already there
            variables = cache.get(f"VARIABLES_{self.room_name}")
            if variables is None:
                variables = dict()
                cache.set(f"VARIABLES_{self.room_name}", dict(), timeout=lock_timeout + BUFFER_TIME)

        # Lead Filters
        self.is_lead = False

        # Session Flag
        session_end = cache.get(f"CLIENTWIDGET_SESSION_END_{self.room_name}")
        if session_end is None:
            self.session_end = False
        else:
            self.session_end = session_end
    

    def flush_session(self, room_name=None, room_id=None):
        if room_name is None:
            room_name = self.room_name
        
        if room_id is None:
            room_id = self.room_id
        
        session_variables = cache.get(f"VARIABLES_{self.room_name}")
        is_lead = cache.get(f"IS_LEAD_{self.room_name}")
        if is_lead != True:
            is_lead = False
        if hasattr(settings, 'CELERY_TASK') and settings.CELERY_TASK == True:
            _ = tasks.flush_db_task.delay(self.room_id, str(self.scope['user']), session_variables, is_lead=is_lead)
        else:
            if self.chatbot_type == 'website':
                # Only flush to DB for website bot
                events.flush_to_db(self.room_id, self.scope['user'], session_variables, is_lead=is_lead)
        
        # Make the chat inactive
        if self.chatbot_type == 'website':
            if (cache.get(f"CLIENTWIDGET_SESSION_END_{self.room_name}") == True) or (hasattr(self, 'session_end') and self.session_end == True):
                # Delete token only if session has ended
                cache.delete(f"CLIENTWIDGET_SESSION_TOKEN_{str(self.room_id)}")
            
            takeover = cache.get(f"CLIENTWIDGET_TAKEOVER_{self.room_name}")

            num_msgs = cache.get(f"CLIENTWIDGET_COUNT_{self.room_name}", 0)
            
            with transaction.atomic():
                if self.room_id is None:
                    ext = cache.get(self.room_id)
                    queryset = ChatRoom.objects.using(ext).filter(room_name=self.room_name)
                else:
                    ext = cache.get(self.room_id)
                    queryset = ChatRoom.objects.using(ext).filter(room_id=self.room_id)
                if queryset.count() == 1:
                    instance = queryset.first()
                    instance.bot_is_active = False
                    instance.num_msgs = num_msgs
                    if hasattr(instance, 'end_time'):
                        instance.end_time = timezone.now()
                    if takeover == True:
                        instance.takeover = True
                    instance.save(send_update=True, using=ext)
            
            # Delete the locks
            cache.delete(f'CLIENTWIDGETROOMLOCK_{self.room_name}') # Lock for the room
            cache.delete(f'CLIENTWIDGETLOCK_{self.room_name}') # Lock for the room messages
            cache.delete(f"CLIENTWIDGETTIMEOUT_{self.room_name}")

            # Delete the expiry lock
            cache.delete(f"CLIENTWIDGET_EXPIRY_LOCK_{self.room_name}")

            if (cache.get(f"CLIENTWIDGET_SESSION_END_{self.room_name}") == True) or (hasattr(self, 'session_end') and self.session_end == True):
                # Only if session has ended
                # Delete the chat information
                cache.delete(f"CLIENTWIDGET_SESSION_END_{self.room_name}")
                cache.delete(f"CLIENTWIDGET_TAKEOVER_{self.room_name}")
                cache.delete(f"CLIENTWIDGET_COUNT_{self.room_name}")
                cache.delete(f'CLIENTWIDGETLEADFIELDS_{self.room_name}')
                cache.delete(f"CLIENTWIDGETLEADDATA_{self.room_name}")
                cache.delete(f'CLIENTWIDGETROOMINFO_{self.room_name}')
                cache.delete(f"CLIENTWIDGETSUBSCRIBED_{self.room_name}")
                cache.delete(f"CLIENTWIDGET_USER_LIST_{self.room_name}")
                cache.delete(f'IS_LEAD_{self.room_name}')
                cache.delete(f'TEAM_{self.room_name}')


    def disconnect(self, close_code):
        """Handler method for disconnection from the LiveChat room websocket.

        On a websocket disconnection, we first decrement the number of users in that room.
        If the number of users drops to 0, we have nobody in that room. Therefore, the session is treated as completed, and we flush the session information into the Database.
        Therefore, the session information (including the history) is now erased after everyone leaves the room.
        """
        # Leave room group
        if not hasattr(self, 'room_group_name') or not hasattr(self, 'room_name'):
            return

        if self.room_id is None or self.room_name is None:
            # In case admin disconnects without the END packet
            if hasattr(self.scope['user'], 'uuid') and self.scope['user'].role in ('AM', 'AO'):
                user_id = self.scope['user'].uuid
                room_list = cache.get(f'CLIENTWIDGET_ROOM_LIST_{user_id}')
                if room_list is not None:
                    room_set = set(room_list)
                    for room_id in room_set:
                        num_users = events.decrement_usercount(room_id)
                        print(f"For {room_id}, num users = {num_users}")
                        if num_users == 0:
                            # Complete the session
                            self.flush_session(room_name=room_id, room_id=room_id)

                    cache.delete(f'CLIENTWIDGET_ROOM_LIST_{user_id}')
            
            print('Disconnected Successfully!')
            if close_code == 400:
                if hasattr(self, 'exception'):
                    if isinstance(self.exception, tuple):
                        exception_type, exception_msg = self.exception[0], self.exception[1]
                        raise LiveChatException(exception_type, exception_msg)
                    else:
                        raise
                else:
                    raise
            return

        async_to_sync(self.channel_layer.group_discard)(
            self.room_group_name,
            self.channel_name
        )
        
        self.num_users = events.decrement_usercount(self.room_name)

        if self.num_users < 0:
            print(f'Having negative number {self.num_users}. Setting to 0...')
            cache.set(f'NUM_USERS_{self.room_name}', 0, timeout=lock_timeout + BUFFER_TIME)

        print(f"Now group has {self.num_users} members")
        logger.info(f"Disconnect: Now Group has {self.num_users} members")
        
        if self.num_users == 0:
            # Nobody's left. Session is over
            if hasattr(settings, 'CELERY_TASK') and settings.CELERY_TASK == True:
                if not hasattr(self, 'session_end'):
                    self.session_end = False
                _ = tasks.flush_session.delay(self.room_name, self.room_id, self.session_end)
            else:
                self.flush_session()

        print("Disconnected Successfully after flushing!")
        
        # Handle exceptions here
        # However, the DB and cache will now be vulnerable to more hits
        if close_code == 400:
            if hasattr(self, 'exception'):
                if isinstance(self.exception, tuple):
                    exception_type, exception_msg = self.exception[0], self.exception[1]
                    raise LiveChatException(exception_type, exception_msg)
                else:
                    raise
            else:
                raise

    # Receive message from WebSocket
    def receive(self, text_data):
        """Handler method on LiveChat websocket receive.

        Websocket Payload Format:

        The websocket payload must be of one of the following formats:
        1.  {
                "user": "admin"
                "message": "Admin Message",
                "time": "timestamp string" (Optional)
                "email": "emailid",
                "first_name": "abcd",
                "last_name": "efgh",
                "room_id": room_id
            }
        
        TODO: Change this for end_user {"message": [{"user": "end_user", "message": {"userInputVal": "xyz"}}], "time": "25/08/2020 07:17:37", "room_name": "cf4f4fc2-374e-40f3-89ab-3573a1dcb069", "user": "bot_parsed", "email": "", "api": false, "first_name": "System", "last_name": "Message"}
        
        2.  {
                "user": "end_user",
                "message": {
                    "userInputVal": "End User Input"
                },
                "time": "timestamp string" (Optional)
                "room_id": room_id
            }
        
        3.  {
                "user": "bot",
                "bot_id": "efefesf42f-frsffsfs3-fsfsfsf",
                "data": {
                            "target_id": "dssdsds434-dsdsds34d-dssd3465",
                            "variable": "@name", ("variable" and "post_data" are optional. They are only needed for variable data input)
                            "post_data": "xyz"
                        }
                "time": "timestamp string" (Optional)
                "room_id": room_id
            }
        
        4.  {
                "user": "bot_parsed",
                "message": [{"user": "admin", "message": "Hello"}, {"user": "end_user", "message": "Hi admin"}]
                "time": "timestamp string" (Optional)
                "room_id": room_id
            }
        
        Notice that in Case 3, sending "message" is not needed. Also notice that we send a list of dictionaries in Case 4
        
        Reply Type:

        If "user" is "admin" / "end_user" / "bot_parsed" , the backend will send the reply of the below format:
        {
            "message": message,
            "time": timestamp,
            
            "room_id": room_id,
            "user": user,
        }

        NOTE: However, if the "user" is "bot", the below response will ensure
        {
            "data": bot_object,
            "time": timestamp,
            "room_id": room_id,
            "user": user,    
        }

        Here, we respond with the bot information in the form of `bot_object`

        After the server responds with a reply, this will append the message content to the session history, if the receive method is successful.
        """
        try:
            session_variables = cache.get(f"VARIABLES_{self.room_name}")
            print(f"Client Widget: Received {text_data} - session = {session_variables}")
            logger.info(f"Client Widget: Received {text_data} - session = {session_variables}")

            text_data_json = json.loads(text_data)
            print(f"{text_data_json}")

            if 'ENTER' in text_data_json and 'room_id' in text_data_json:
                # Connection from admin / operator
                try:
                    room_id = str(text_data_json['room_id'])
                    if hasattr(self.scope['user'], 'uuid') and self.scope['user'].role in ('AM', 'AO'):
                        user_id = str(self.scope['user'].uuid)
                        print(user_id)
                        if cache.get(f"CLIENTWIDGET_MAP_{user_id}_{room_id}") is None:
                            cache.set(f"CLIENTWIDGET_MAP_{user_id}_{room_id}", True, timeout=lock_timeout + BUFFER_TIME)

                            self.num_users = events.increment_usercount(room_id)
                            logger.info(f"Now, num_users = {self.num_users}")
                            
                            user_list = cache.get(f'CLIENTWIDGET_USER_LIST_{room_id}')
                            room_list = cache.get(f"CLIENTWIDGET_ROOM_LIST_{user_id}")
                            
                            if user_list is None:
                                user_list = []
                            
                            if room_list is None:
                                room_list = []
                            
                            user_set = set(user_list)
                            if user_id not in user_set:
                                user_set.add(user_id)
                                cache.set(f'CLIENTWIDGET_USER_LIST_{room_id}', list(user_set))
                            
                            room_set = set(room_list)
                            if room_id not in room_set:
                                room_set.add(room_id)
                                cache.set(f'CLIENTWIDGET_ROOM_LIST_{user_id}', list(room_set))
                except Exception as ex:
                    print(ex)
                return

            if 'EXIT' in text_data_json and 'room_id' in text_data_json:
                # Timeout from admin / operator
                try:
                    room_id = str(text_data_json['room_id'])
                    if hasattr(self.scope['user'], 'uuid') and self.scope['user'].role in ('AM', 'AO'):
                        user_id = str(self.scope['user'].uuid)
                        if cache.get(f"CLIENTWIDGET_MAP_{user_id}_{room_id}") is not None:
                            self.num_users = events.decrement_usercount(room_id)
                            logger.info(f"Now, num_users = {self.num_users}")
                            cache.delete(f"CLIENTWIDGET_MAP_{user_id}_{room_id}")
                            
                            user_list = cache.get(f'CLIENTWIDGET_USER_LIST_{room_id}')
                            
                            if user_list is not None:                    
                                user_set = set(user_list)
                                user_set.discard(user_id)
                                if user_list != set():
                                    cache.set(f'CLIENTWIDGET_USER_LIST_{room_id}', list(user_set))
                                else:
                                    cache.delete(f'CLIENTWIDGET_USER_LIST_{room_id}')

                            room_list = cache.get(f'CLIENTWIDGET_ROOM_LIST_{user_id}')
                            
                            if room_list is not None:
                                room_set = set(room_list)
                                room_set.discard(room_id)
                                cache.set(f'CLIENTWIDGET_ROOM_LIST_{user_id}', list(room_set))
                            
                            if self.num_users == 0:
                                # Disconnect
                                self.disconnect(200)
                except Exception as ex:
                    print(ex)
                return

            if 'user' not in text_data_json:
                self.exception = ("PayloadFormatError", "No \"user\" field in websocket payload")
                self.disconnect(400)

            user = text_data_json['user']

            email = ''

            first_name = ''
            last_name = ''

            if 'first_name' in text_data_json:
                first_name = text_data_json['first_name']
            else:
                if not hasattr(self.scope['user'], 'first_name'):
                    first_name = 'Anonymous'
                else:
                    first_name = getattr(self.scope['user'], 'first_name')
                text_data_json['first_name'] = first_name

            if 'last_name' in text_data_json:
                last_name = text_data_json['last_name']
            else:
                if not hasattr(self.scope['user'], 'last_name'):
                    last_name = 'User'
                else:
                    last_name = getattr(self.scope['user'], 'last_name')
                text_data_json['last_name'] = last_name

            if 'time' in text_data_json:
                timestamp = text_data_json['time']
            else:
                timestamp = timezone.now().strftime("%d/%m/%Y %H:%M:%S") # Current time
                text_data_json['time'] = timestamp
            
            if 'room_id' in text_data_json:
                room_id = text_data_json['room_id']
            else:
                room_id = str(self.room_id)
                text_data_json['room_id'] = str(room_id)

            if user in ('admin', 'operator'):
                if 'email' not in text_data_json:
                    if hasattr(self.scope['user'], 'email'):
                        email = self.scope['user'].email
                    else:
                        if self.chatbot_type == 'website':
                            self.exception = ("PayloadFormatError", "No \"email\" field in websocket payload for user=admin / user=operator")
                            self.disconnect(400)
                        else:
                            print(f"Whatsapp Bot warning. Please set email field in payload")
                            email = ''
                    text_data_json['email'] = email
                else:
                    email = text_data_json['email']
            
            elif user == 'end_user':
                email = ''
            
            owner_id = str(self.owner_id)

            if user in ('end_user', 'admin', 'operator'):
                if 'message' not in text_data_json:
                    self.exception = ("PayloadFormatError", "No \"message\" field in websocket payload for user=admin / user=end_user")
                    self.disconnect(400)

                message = text_data_json['message']
                    
                if hasattr(self, 'chatbot_type') and self.chatbot_type == 'whatsapp' and user in ('admin', 'operator'):
                    # Send a POST request using the shared client
                    try:
                        response = shared_client.post(f'{server_addr}/api/whatsappbot/agenttakeover/{self.room_name}', json={'user': user, 'message': message})
                    except:
                        self.disconnect(400)
                    
                    if response.status_code in (200, 201):
                        events.append_msg_to_redis(self.room_name, text_data_json, store_full=True)
                    else:
                        print('Error during POST request when sending from user=admin')
                        async_to_sync(self.channel_layer.group_send)(
                            self.room_group_name,
                            {
                                'type': 'chat_message',
                                'message': f'POST request error - Returned Code: {response.status_code}',
                                'time': timestamp,
                                'room_id': str(room_id),
                                'user': 'Server',
                                'first_name': 'System',
                                'last_name': 'Message',
                            }
                        )

                else:
                    # Send using websockets
                    if user == 'end_user':
                        # Sender Group
                        group_name = self.sender_group_name
                        receiver_group_name = self.receiver_group_name
                    else:
                        # Admin / operator sends to Receiver Group based on the room_id
                        if room_id is None:
                            receiver_group_name = self.receiver_group_name
                        else:
                            receiver_group_name = room_id
                    
                    if hasattr(settings, 'CELERY_TASK') and settings.CELERY_TASK == True:
                        _ = tasks.send_user_message.delay(
                            [self.sender_group_name, receiver_group_name], event={
                                'message': message,
                                'time': timestamp,
                                'room_id': str(room_id),
                                'owner_id': str(owner_id),
                                'user': user,
                                'email': email,
                                'first_name': first_name,
                                'last_name': last_name, 
                            }, data=text_data_json, store_full=True,
                        )
                    else:
                        async_to_sync(self.channel_layer.group_send)(
                            str(room_id),
                            {
                                'type': 'chat_message',
                                'message': message,
                                'time': timestamp,
                                'room_id': str(room_id),
                                'owner_id': str(owner_id),
                                'user': user,
                                'email': email,
                                'first_name': first_name,
                                'last_name': last_name,
                            }
                        )

                        async_to_sync(self.channel_layer.group_send)(
                            str(owner_id),
                            {
                                'type': 'chat_message',
                                'message': message,
                                'time': timestamp,
                                'room_id': str(room_id),
                                'owner_id': str(owner_id),
                                'user': user,
                                'email': email,
                                'first_name': first_name,
                                'last_name': last_name,
                            }
                        )

                        # Send to operator group
                        team_operators = cache.get(f"TEAM_{room_id}")
                        if team_operators is not None:
                            for team in team_operators:
                                _team = team.replace(" ", "")
                                async_to_sync(self.channel_layer.group_send)(
                                    'operator_team_{}_{}'.format(owner_id, str(_team)),
                                    {
                                        'type': 'chat_message',
                                        'message': message,
                                        'time': timestamp,
                                        'room_id': str(room_id),
                                        'owner_id': str(owner_id),
                                        'user': user,
                                        'email': email,
                                        'first_name': first_name,
                                        'last_name': last_name,
                                    }
                                )
                        else:
                            client_map = cache.get(f"CLIENT_MAP_{owner_id}")
                            if client_map is not None and room_id in client_map:
                                operator_id = client_map[room_id]

                                #TODO: Need To add Celery
                                logger.info(f'chats_op---->{operator_id}')
                                for operator in operator_id:
                                    async_to_sync(self.channel_layer.group_send)(
                                        operator,
                                        {
                                            'type': 'chat_message',
                                            'message': message,
                                            'time': timestamp,
                                            'room_id': str(room_id),
                                            'owner_id': str(owner_id),
                                            'user': user,
                                            'email': email,
                                            'first_name': first_name,
                                            'last_name': last_name,
                                        }
                                    )

                        # Append contents to Redis List
                        events.append_msg_to_redis(room_id, text_data_json, store_full=True)
                        num_msgs = cache.get(f"CLIENTWIDGET_COUNT_{room_id}", 0)
                        num_msgs += 1
                        cache.set(f"CLIENTWIDGET_COUNT_{room_id}", num_msgs, timeout=lock_timeout + BUFFER_TIME)
            
            elif user == 'bot':
                for reqd_field in set({'bot_id', 'data'}):
                    if reqd_field not in text_data_json:
                        self.exception = ("PayloadFormatError", f"No \"{reqd_field}\" field in websocket payload for user=bot")
                        self.disconnect(400) # Disconnect from the channel first

                bot_id = text_data_json['bot_id']
                data = text_data_json['data']

                message = text_data_json['message'] if 'message' in text_data_json else None

                if 'target_id' not in data:
                    self.exception = ("PayloadFormatError", f"No \"target_id\" field in \"data\" of payload for user=bot")
                    self.disconnect(400) # Disconnect from the channel first

                target_id = data['target_id']
                variable, value = (data['variable'] if 'variable' in data else None, data['post_data'] if 'post_data' in data else None)

                if variable is not None and value is not None:
                    session_variables = cache.get(f"VARIABLES_{self.room_name}")
                    session_variables[variable] = value
                    cache.set(f"VARIABLES_{self.room_name}", session_variables, timeout=lock_timeout + BUFFER_TIME)
                    
                    variables = cache.get(f"VARIABLES_{self.room_name}")

                    if variables is None:
                        variables = {}
                        cache.set(f"VARIABLES_{self.room_name}", variables, timeout=lock_timeout + BUFFER_TIME)

                    variables[variable] = value

                    # TODO: Add Celery task for cache setting
                    cache.set(f"VARIABLES_{self.room_name}", variables, timeout=lock_timeout + BUFFER_TIME)

                    # Check if the user matches a lead
                    if not self.is_lead:
                        status = self.check_if_lead(variable, value)
                        if status:
                            # Set the flag
                            cache.set(f"IS_LEAD_{self.room_name}", True, timeout=lock_timeout + BUFFER_TIME)
                            
                            # Send an email -> Background Task
                            if False:
                                # TODO: Remove this
                                if hasattr(self, 'is_subscribed') and self.is_subscribed == True:
                                    # Background task
                                    try:
                                        lead_data = cache.get(f"VARIABLES_{self.room_name}")
                                        lead_fields = cache.get(f"CLIENTWIDGETLEADDATA_{self.room_name}")
                                        if lead_fields is not None and lead_data is not None:
                                            lead_data = {key: value for key, value in lead_data.items() if key in lead_fields}
                                        if hasattr(settings, 'CELERY_TASK') and settings.CELERY_TASK == True:
                                            _ = tasks.chat_lead_send_update.delay(self.room_id, lead_data)
                                        else:
                                            _thread.start_new_thread(chat_lead_send_update, (self.room_id, lead_data))
                                    except Exception as ex:
                                        print(ex)

                if 'time' in text_data_json:
                    timestamp = text_data_json['time']
                else:
                    timestamp = timezone.now().strftime("%d/%m/%Y %H:%M:%S")
                    text_data_json['time'] = timestamp
                
                if 'owner_id' in text_data_json:
                    owner_id = str(text_data_json['owner_id'])
                else:
                    owner_id = str(self.owner_id)
                            
                # Go to the corresponding target_id None
                logger.info(f"Target id = {target_id}")
                bot_obj, var_obj, _, _ = self.get_bot_data(bot_id, bot_com_tid=target_id)
                var_obj = cache.get(f"VARIABLES_{self.room_name}")
                if var_obj is None:
                    var_obj = dict()

                if bot_obj is None or var_obj is None:
                    # Bot error. Deactivate
                    logger.critical("Error during fetching bot details. Disconnecting...")
                    self.disconnect(200)
                
                bot_obj = {**bot_obj, 'variables': var_obj}

                reply = {
                    'data': bot_obj,
                    'time': timestamp,
                    'room_id': str(room_id),
                    'owner_id': str(owner_id),
                    'message': message,
                    'user': user,
                    'first_name': 'System',
                    'last_name': 'Message',
                }

                # Send message to room group
                if hasattr(settings, 'CELERY_TASK') and settings.CELERY_TASK == True:
                    _ = tasks.send_template_message.delay(
                        self.sender_group_name, self.receiver_group_name, reply,
                        self.room_name, message, store_full=True,
                    )
                else:
                    async_to_sync(self.channel_layer.group_send)(
                        self.sender_group_name, {
                            'type': 'template_message',
                            **reply,
                        }
                    )

                    if self.room_name is not None:
                        async_to_sync(self.channel_layer.group_send)(
                            self.receiver_group_name, {
                                'type': 'template_message',
                                **reply,
                            }
                        )
                    
                    # Send to operator group
                    client_map = cache.get(f"CLIENT_MAP_{owner_id}")
                    if client_map is not None and room_id in client_map:
                        operator_id = client_map[room_id]
                        for operator in operator_id:
                            async_to_sync(self.channel_layer.group_send)(
                                operator,
                                {
                                    'type': 'template_message',
                                    **reply,
                                }
                            )

                    # Append the BOT response to Redis List
                    events.append_msg_to_redis(self.room_name, reply, store_full=True)
                    if self.exclude_count == False:
                        num_msgs = cache.get(f"CLIENTWIDGET_COUNT_{self.room_name}", 0)
                        num_msgs += 1
                        cache.set(f"CLIENTWIDGET_COUNT_{self.room_name}", num_msgs, timeout=lock_timeout + BUFFER_TIME)
                    else:
                        # Set to false again
                        self.exclude_count = False
            
            elif user == 'session_timeout':
                async_to_sync(self.channel_layer.group_send)(
                    self.sender_group_name, {
                        'type': 'chat_message',
                        'room_id': str(room_id),
                        'owner_id': str(owner_id),
                        'message': 'Session Timeout',
                        'time': timezone.now().strftime("%d/%m/%Y %H:%M:%S"),
                        'user': user,
                        'first_name': 'System',
                        'last_name': 'Message',
                    }
                )
            
            # Now update the Timestamp
            cache.set(f"CLIENTWIDGETTIMEOUT_{self.room_name}", timezone.now().strftime("%d/%m/%Y %H:%M:%S"), timeout=lock_timeout)
        except LiveChatException:
            raise
        except Exception as ex:
            logger.critical(f"Disconnecting... Error with ClientwidgetConsumer: {ex}")
            self.disconnect(400)


    # Template messages
    def template_message(self, event):
        data = event['data']
        timestamp = event['time']
        message = event['message']
        user = event['user']
        first_name = event['first_name'] if 'first_name' in event else 'System'
        last_name = event['last_name'] if 'last_name' in event else 'Message'
        room_id = event['room_id'] if 'room_id' in event else self.room_id
        owner_id = event['owner_id'] if 'owner_id' in event else self.owner_id
        self.send(text_data=json.dumps({
                'data': data,
                'time': timestamp,
                'message': message,
                'user': user,
                'first_name': first_name,
                'last_name': last_name,
                'room_id': str(room_id),
                'owner_id': str(owner_id),
            }))
        #self.num_msgs += 1
    
    # Livechat messages
    def chat_message(self, event):
        message = event['message']
        timestamp = event['time']
        room_id = event['room_id']
        user = event['user']
        if 'email' in event:
            email = event['email']
        else:
            email = ''
        first_name = event['first_name'] if 'first_name' in event else 'Anonymous'
        last_name = event['last_name'] if 'last_name' in event else 'User'
        owner_id = event['owner_id'] if 'owner_id' in event else self.owner_id
        print(message, user)
        logger.info(f"{message}, {user}")
        if "api" in event:
            self.send(text_data=json.dumps({
                'message': message,
                'time': timestamp,
                'room_id': str(room_id),
                'owner_id': str(owner_id),
                'user': user,
                'email': email,
                'api': True,
                'first_name': first_name,
                'last_name': last_name,
            }))
        else:
            self.send(text_data=json.dumps({
                'message': message,
                'time': timestamp,
                'room_id': str(room_id),
                'owner_id': str(owner_id),
                'user': user,
                'email': email,
                'api': False,
                'first_name': first_name,
                'last_name': last_name,
            }))
    
    def chat_status_update(self, event):
        self.send(text_data=json.dumps(
            event
        ))
    
    @staticmethod
    def send_highlights(message, room_id, time, secret=False):
        channel_layer = get_channel_layer()
        group_name = str(room_id)
        message = {
            "highlights": str(message),
            "room_id": str(room_id),
            "secret": secret,
            "time": time
        }
        async_to_sync(channel_layer.group_send)(
            group_name,
            {
                'type': 'chat_status_update',
                **message
            }
        )
    
    
    @staticmethod
    def send_from_api(room_id, receiver_ids, message_dict, bot_type='website', owner_id=None):
        channel_layer = get_channel_layer()
        for ids in receiver_ids:
            group_name = str(ids)
            
            async_to_sync(channel_layer.group_send)(
            group_name,
            {
                "type": "chat_message",
                **message_dict,
            })
        
        # Send to operators also
        try:
            if owner_id is not None:
                send_to_operator(str(room_id), owner_id, channel_layer, message_dict)
        except Exception as ex:
            logger.critical(f"{ex}")
    
    @staticmethod
    def send_status(room_id):
        channel_layer = get_channel_layer()
        group_name = str(room_id)
        message_dict = {
            "update_status": "true",
            "start_over": "true"
        }
        async_to_sync(channel_layer.group_send)(
            group_name,
            {
                "type": "chat_status_update",
                **message_dict
            }
        )

@log_consumer_exceptions
class AdminConsumer(WebsocketConsumer):
    """Websocket Consumer for the Admin
    """

    def get_group_name(self):
        pass


    def connect(self):
        if 'owner_id' in self.scope['url_route']['kwargs']:
            self.owner_id = self.scope['url_route']['kwargs']['owner_id']
        else:
            self.owner_id = None

        self.group_name = str(self.owner_id)

        self.sender_group_name = self.group_name
        
        self.receiver_group_name = self.sender_group_name

        #if hasattr(self.scope['user'], 'role') and self.scope['user'].role in ('AM'):
            # Only admins can enter
            # pass
        async_to_sync(self.channel_layer.group_add)(
            self.group_name,
            self.channel_name
        )
        print(f"Admin now added to group {self.group_name}")

        print(f"group name = {self.group_name}")
        logger.info(f"group name = {self.group_name}")

        self.user = self.scope['user']
        print(f'user is {self.user}')
        logger.info(f'user is {self.user}')

        try:
            print("User email is" + self.scope['user'].email)
        except:
            pass
        
        self.accept()

        # Set bot_type to None initially
        self.bot_type = None

        self.has_entered = False

        self.last_room_id = None


    def disconnect(self, close_code):
        # Leave room group

        if hasattr(self, 'last_room_id') and cache.get(f"NUM_USERS_{self.last_room_id}", 100) <= 0:
            # Set the session end flag
            cache.set(f"CLIENTWIDGET_SESSION_END_{self.last_room_id}", True, timeout=lock_timeout + BUFFER_TIME)

        if not hasattr(self, 'group_name'):
            return

        if close_code == 400:
            print("Unauthorised User. Only admins can access this socket")
            return

        if hasattr(self, 'has_entered') and self.has_entered == True:
            # We need to send the disconnect packet explicitly as admin left abnormally
            if hasattr(self, 'last_room_id') and self.last_room_id is not None:
                try:
                    self.send_exit_msg(self.last_room_id, "Admin has disconnected from the Chat", override=True)
                    self.last_room_id = None
                    self.has_entered = False
                except Exception as ex:
                    print(ex)

        async_to_sync(self.channel_layer.group_discard)(
            self.group_name,
            self.channel_name
        )

        print('Disconnected Successfully!')
        return
    

    def send_enter_msg(self, room_id, db_label, msg):
        try:
            num_users = events.increment_usercount(room_id)
            logger.info(f"Now, num_users = {num_users}")

            logger.info(f"Before, bot type = {self.bot_type}")

            if self.bot_type is None:
                try:
                    bot_room_id = uuid.UUID(room_id)
                    logger.info(f"ROOM ID = {bot_room_id}")
                    bot_id = ChatRoom.objects.using(db_label).get(room_id=bot_room_id).bot_id
                    logger.info(f"BOT ID = {bot_id}")
                    bot_type = Chatbox.objects.get(pk=bot_id).chatbot_type
                    self.bot_type = bot_type
                    logger.info(f"Bot Type = {self.bot_type}")
                except Exception as ex:
                    print(ex)
                    logger.info(f"{ex}")
            
            logger.info(f"After, bot_type = {self.bot_type}")
            
            """
            if self.bot_type == 'website':
                try:
                    template = {
                        "room_id": str(room_id),
                        "user": "admin",
                        "first_name": "System",
                        "last_name": "Message",
                        "email": "system",
                        "time": timezone.now().strftime("%d/%m/%Y %H:%M:%S"),
                        "message": msg,
                    }

                    async_to_sync(self.channel_layer.group_send)(
                        str(room_id),
                        {
                            **template,
                            'type': 'chat_message',
                        }
                    )

                    if hasattr(self, 'has_entered') and self.has_entered == False:
                        # Send to admin group also, as this is a normal connect
                        async_to_sync(self.channel_layer.group_send)(
                            str(self.owner_id),
                            {
                                **template,
                                'type': 'chat_message',
                            }
                        )

                    send_to_operator(str(room_id), self.owner_id, self.channel_layer, template)

                except Exception as ex:
                    print(ex)

            if self.bot_type in ['whatsapp', 'facebook']:
                try:
                    logger.info(f"Calling Send Admin Message with room_id {room_id}")
                    send_admin_message(room_id, msg, self.bot_type, enter_chat=True, api=False)
                except Exception as ex:
                    print(ex)
                    logger.info(f"{ex}")
            """

            # Set the takeover flag
            cache.set(f"CLIENTWIDGET_TAKEOVER_{room_id}", True, timeout=lock_timeout + BUFFER_TIME)
        except Exception as ex:
            print(ex)
    

    def send_exit_msg(self, room_id, msg, override=False):
        try:
            num_users = events.decrement_usercount(room_id)
            logger.info(f"Now, num_users = {num_users}")

            if cache.get(f"NUM_USERS_{room_id}", 100) <= 0:
                # Set the session end flag
                cache.set(f"CLIENTWIDGET_SESSION_END_{room_id}", True, timeout=lock_timeout + BUFFER_TIME)

            if override == True:
                if self.bot_type == 'website':
                    try:
                        template = {
                            "room_id": str(room_id),
                            "user": "admin",
                            "first_name": "System",
                            "last_name": "Message",
                            "email": "system",
                            "time": timezone.now().strftime("%d/%m/%Y %H:%M:%S"),
                            "message": msg,
                        }

                        async_to_sync(self.channel_layer.group_send)(
                            str(room_id),
                            {
                                **template,
                                'type': 'chat_message',
                            }
                        )

                        if hasattr(self, 'has_entered') and self.has_entered == False:
                            # Send to admin group also, as this is a normal disconnect
                            async_to_sync(self.channel_layer.group_send)(
                                str(self.owner_id),
                                {
                                    **template,
                                    'type': 'chat_message',
                                }
                            )

                        send_to_operator(room_id, self.owner_id, self.channel_layer, template)

                    except Exception as ex:
                        print(ex)

            if num_users <= 0 and self.bot_type == "website":
                # Flushing session
                [events.increment_usercount(room_id) for _ in range(0 - num_users)]
                if hasattr(settings, 'CELERY_TASK') and settings.CELERY_TASK == True:
                    _ = tasks.flush_session.delay(room_id, room_id, False)
                else:
                    tasks.flush_session(room_id, room_id, False)
                return
        except Exception as ex:
            print(ex)


    # Receive message from WebSocket
    def receive(self, text_data):
        print(f"Admin Consumer: Received {text_data}")
        logger.info(f"Admin Consumer: Received {text_data}")

        text_data_json = json.loads(text_data)
        print(f"{text_data_json}")

        fields = ('user', 'room_id')
        for field in fields:
            if field not in text_data_json:
                print("No user / room_id  field in data. Stopping processing this packet")
                return
        
        user = text_data_json['user']
        room_id = text_data_json['room_id']

        db_label = cache.get(str(room_id)) # TODO: Change this
        
        owner_id = str(self.owner_id)

        if 'ENTER' in text_data_json:
            # Connection from admin / operator
            self.send_enter_msg(room_id, db_label, "Admin has now entered the Chat")
            self.has_entered = True
            self.last_room_id = room_id
            return

        if 'EXIT' in text_data_json and 'room_id' in text_data_json:
            # Timeout from admin / operator
            self.has_entered = False
            self.last_room_id = None
            self.send_exit_msg(room_id, "Admin has exited the Chat")
            return

        if 'time' not in text_data_json:
            text_data_json['time'] = timezone.now().strftime("%d/%m/%Y %H:%M:%S")
        
        if user == 'session_timeout':
            async_to_sync(self.channel_layer.group_send)(
                room_id, {
                    'type': 'chat_message',
                    'room_id': room_id,
                    'owner_id': owner_id,
                    'message': 'Session Timeout',
                    'time': timezone.now().strftime("%d/%m/%Y %H:%M:%S"),
                    'user': user,
                    'first_name': 'System',
                    'last_name': 'Message',
                }
            )
        
        if hasattr(settings, 'CELERY_TASK') and settings.CELERY_TASK == True:
            _ = tasks.send_admin_message.delay(
                [self.sender_group_name, self.receiver_group_name], event={
                    **text_data_json 
                }, data=text_data_json, store_full=True,
            )
        else:
            try:
                if user == 'admin':
                    try:
                        text_data_json['first_name'] = self.scope['user'].first_name
                        text_data_json['last_name'] = self.scope['user'].last_name
                        text_data_json['email'] = self.scope['user'].email
                    except Exception as ex:
                        text_data_json['email'] = ''
                        print(ex)
                    
                    async_to_sync(self.channel_layer.group_send)(
                        str(room_id),
                        {
                            **text_data_json,
                            'type': 'chat_message',
                        }
                    )
                    
                    try:
                        client_map = cache.get(f"CLIENT_MAP_{owner_id}")
                        print(f"CLIENT MAP = {client_map}")
                        logger.info(f"CLIENT MAP = {client_map}")
                        if client_map is not None:
                            operator_id = client_map.get(room_id)
                            #TODO: Need to add celery tas here
                            for operator in operator_id:
                                async_to_sync(self.channel_layer.group_send)(
                                    operator,
                                    {
                                        **text_data_json,
                                        'type': 'chat_message',
                                    }
                                )
                    except Exception as ex:
                        print(ex)

                async_to_sync(self.channel_layer.group_send)(
                    str(owner_id),
                    {
                        **text_data_json,
                        'type': 'chat_message',
                    }
                )

                if user == 'admin':
                    try:
                        if self.bot_type is None:
                            pass
                    except Exception as ex:
                        print(f"Exception during sending Whatsapp message from admin: {ex}")

                events.append_msg_to_redis(room_id, text_data_json, store_full=True)
                num_msgs = cache.get(f"CLIENTWIDGET_COUNT_{room_id}", 0)
                num_msgs += 1
                cache.set(f"CLIENTWIDGET_COUNT_{room_id}", num_msgs, timeout=lock_timeout + BUFFER_TIME)
            
            except Exception as ex:
                print(ex)

    def template_message(self, event):
        try:
            self.send(text_data=json.dumps(event))
        except Exception as ex:
            print(ex)
    
    # Livechat messages
    def chat_message(self, event):
        try:
            self.send(text_data=json.dumps(event))
        except Exception as ex:
            print(ex)
    
    @staticmethod
    def send_highlights(message, room_id, owner_id, time, secret=False):
        channel_layer = get_channel_layer()
        group_name = str(owner_id)
        message = {
            "highlights": str(message),
            "room_id": str(room_id),
            "secret": secret,
            "time": time
        }
        events.append_msg_to_redis(room_id, message, store_full=True)
        async_to_sync(channel_layer.group_send)(
            group_name,
            {
                'type': 'chat_message',
                **message
            }
        )


@log_consumer_exceptions
class OperatorConsumer(WebsocketConsumer):
    """Websocket Consumer for the Operator
    """

    def get_group_name(self):
        pass


    def connect(self):
        if 'operator_id' in self.scope['url_route']['kwargs']:
            self.operator_id = self.scope['url_route']['kwargs']['operator_id']
        else:
            self.operator_id = None

        if 'owner_id' in self.scope['url_route']['kwargs']:
            self.owner_id = self.scope['url_route']['kwargs']['owner_id']
        else:
            self.owner_id = None

        self.group_name = str(self.operator_id)

        self.sender_group_name = self.group_name
        
        self.receiver_group_name = self.sender_group_name

        async_to_sync(self.channel_layer.group_add)(
            self.group_name,
            self.channel_name
        )
        self.user = User.objects.get(uuid=self.operator_id)
        if self.user is not None and self.user.team_member is not None:
            team_name = self.user.team_member.name.replace(" ", "")
            self.team_group_name = 'operator_team_{}_{}'.format(self.user.operator_of.uuid, team_name)

            async_to_sync(self.channel_layer.group_add)(
            self.team_group_name,
            self.channel_name
            )

        print(f"Operator now added to group {self.group_name}")

        print(f"group name = {self.group_name}")
        logger.info(f"group name = {self.group_name}")

        self.user = str(self.scope['user'])
        print(f'user is {self.user}')
        logger.info(f'user is {self.user}')
        
        self.accept()

        self.bot_type = None

        self.has_entered = False

        self.last_room_id = None


    def disconnect(self, close_code):
        # Leave room group
        if not hasattr(self, 'group_name'):
            return

        if hasattr(self, 'last_room_id') and cache.get(f"NUM_USERS_{self.last_room_id}", 100) <= 0:
            # Set the session end flag
            cache.set(f"CLIENTWIDGET_SESSION_END_{self.last_room_id}", True, timeout=lock_timeout + BUFFER_TIME)

        if close_code == 400:
            print("Unauthorised User. Only operators can access this socket")
            return

        if hasattr(self, 'has_entered') and self.has_entered == True:
            # We need to send the disconnect packet explicitly as operator left abnormally
            if hasattr(self, 'last_room_id') and self.last_room_id is not None:
                try:
                    self.send_exit_msg(self.last_room_id, "Operator has disconnected from the Chat", override=True)
                    self.last_room_id = None
                    self.has_entered = False
                except Exception as ex:
                    print(ex)

        async_to_sync(self.channel_layer.group_discard)(
            self.group_name,
            self.channel_name
        )

        print('Disconnected Successfully!')
        return


    def send_enter_msg(self, room_id, db_label, msg):
        try:
            num_users = events.increment_usercount(room_id)
            logger.info(f"Now, num_users = {num_users}")

            logger.info(f"Before, bot type = {self.bot_type}")

            if self.bot_type is None:
                try:
                    bot_room_id = uuid.UUID(room_id)
                    logger.info(f"ROOM ID = {bot_room_id}")
                    bot_id = ChatRoom.objects.using(db_label).get(room_id=bot_room_id).bot_id
                    logger.info(f"BOT ID = {bot_id}")
                    bot_type = Chatbox.objects.get(pk=bot_id).chatbot_type
                    self.bot_type = bot_type
                    logger.info(f"Bot Type = {self.bot_type}")
                except Exception as ex:
                    print(ex)
                    logger.info(f"{ex}")
            
            logger.info(f"After, bot_type = {self.bot_type}")

            """
            if self.bot_type == 'website':
                try:
                    template = {
                        "room_id": str(room_id),
                        "user": "operator",
                        "first_name": "System",
                        "last_name": "Message",
                        "email": "system",
                        "time": timezone.now().strftime("%d/%m/%Y %H:%M:%S"),
                        "message": msg,
                    }

                    async_to_sync(self.channel_layer.group_send)(
                        str(room_id),
                        {
                            **template,
                            'type': 'chat_message',
                        }
                    )

                    async_to_sync(self.channel_layer.group_send)(
                        str(self.owner_id),
                        {
                            **template,
                            'type': 'chat_message',
                        }
                    )

                    if hasattr(self, 'has_entered') and self.has_entered == True:
                        # Send to operator group also, as this is a normal connect
                        async_to_sync(self.channel_layer.group_send)(
                            str(self.operator_id),
                            {
                                **template,
                                'type': 'chat_message',
                            }
                        )
                except Exception as ex:
                    print(ex)

            if self.bot_type in ['whatsapp', 'facebook']:
                try:
                    logger.info(f"Calling Send Admin Message with room_id {room_id}")
                    send_admin_message(room_id, msg, self.bot_type, enter_chat=True, api=False)
                except Exception as ex:
                    print(ex)
                    logger.info(f"{ex}")
            """
            
            # Set the takeover flag
            cache.set(f"CLIENTWIDGET_TAKEOVER_{room_id}", True, timeout=lock_timeout + BUFFER_TIME)

            # Set the session end flag
            cache.set(f"CLIENTWIDGET_SESSION_END_{room_id}", True, timeout=lock_timeout + BUFFER_TIME)
        except Exception as ex:
            print(ex)
    
    
    def send_exit_msg(self, room_id, msg, override=False):
        try:
            num_users = events.decrement_usercount(room_id)
            logger.info(f"Now, num_users = {num_users}")

            if cache.get(f"NUM_USERS_{room_id}", 100) <= 0:
                # Set the session end flag
                cache.set(f"CLIENTWIDGET_SESSION_END_{room_id}", True, timeout=lock_timeout + BUFFER_TIME)

            if override == True:
                if self.bot_type == 'website':
                    try:
                        template = {
                            "room_id": str(room_id),
                            "user": "operator",
                            "first_name": "System",
                            "last_name": "Message",
                            "email": "system",
                            "time": timezone.now().strftime("%d/%m/%Y %H:%M:%S"),
                            "message": msg,
                        }

                        async_to_sync(self.channel_layer.group_send)(
                            str(room_id),
                            {
                                **template,
                                'type': 'chat_message',
                            }
                        )

                        async_to_sync(self.channel_layer.group_send)(
                            str(self.owner_id),
                            {
                                **template,
                                'type': 'chat_message',
                            }
                        )

                        if hasattr(self, 'has_entered') and self.has_entered == False:
                            # Send to operator group also, as this is a normal disconnect
                            async_to_sync(self.channel_layer.group_send)(
                                str(self.operator_id),
                                {
                                    **template,
                                    'type': 'chat_message',
                                }
                            )

                    except Exception as ex:
                        print(ex)

            if num_users <= 0 and self.bot_type == "website":
                # Flushing session
                [events.increment_usercount(room_id) for _ in range(0 - num_users)]
                if hasattr(settings, 'CELERY_TASK') and settings.CELERY_TASK == True:
                    _ = tasks.flush_session.delay(room_id, room_id, False)
                else:
                    tasks.flush_session(room_id, room_id, False)
                return
        except Exception as ex:
            print(ex)
    

    # Receive message from WebSocket
    def receive(self, text_data):
        print(f"Operator Consumer: Received {text_data}")
        logger.info(f"Operator Consumer: Received {text_data}")

        text_data_json = json.loads(text_data)
        print(f"{text_data_json}")

        fields = ('user', 'room_id')
        for field in fields:
            if field not in text_data_json:
                print("No user / room_id  field in data. Stopping processing this packet")
                return
        
        user = text_data_json['user']
        room_id = text_data_json['room_id']
        owner_id = str(self.owner_id)

        db_label = cache.get(str(room_id)) # TODO: Change this

        if 'ENTER' in text_data_json:
            # Connection from admin / operator
            self.send_enter_msg(room_id, db_label, "Operator has now entered the Chat")
            self.has_entered = True
            self.last_room_id = room_id
            return

        if 'EXIT' in text_data_json and 'room_id' in text_data_json:
            # Timeout from admin / operator
            self.has_entered = False # We unset the flag BEFORE actually leaving. This is useful if the operator disconnects abnormally
            self.last_room_id = None
            self.send_exit_msg(room_id, "Operator has exited the Chat")
            return

        if 'time' not in text_data_json:
            text_data_json['time'] = timezone.now().strftime("%d/%m/%Y %H:%M:%S")

        if user == 'session_timeout':
            async_to_sync(self.channel_layer.group_send)(
                room_id, {
                    'type': 'chat_message',
                    'room_id': room_id,
                    'message': 'Session Timeout',
                    'time': timezone.now().strftime("%d/%m/%Y %H:%M:%S"),
                    'user': user,
                    'first_name': 'System',
                    'last_name': 'Message',
                }
            )
        
        if hasattr(settings, 'CELERY_TASK') and settings.CELERY_TASK == True:
            _ = tasks.send_admin_message.delay(
                [self.sender_group_name, self.receiver_group_name], event={
                    **text_data_json 
                }, data=text_data_json, store_full=True,
            )
        else:
            try:
                if user == 'operator':
                    try:
                        text_data_json['first_name'] = self.scope['user'].first_name
                        text_data_json['last_name'] = self.scope['user'].last_name
                        text_data_json['email'] = self.scope['user'].email
                    except Exception as ex:
                        text_data_json['email'] = ''
                        print(ex)
                    
                    logger.info(f"OPERATOR SENDING room_id {room_id}, OWNER ID {owner_id}")

                    async_to_sync(self.channel_layer.group_send)(
                        room_id,
                        {
                            **text_data_json,
                            'type': 'chat_message',
                        }
                    )

                    async_to_sync(self.channel_layer.group_send)(
                        owner_id,
                        {
                            **text_data_json,
                            'type': 'chat_message',
                        }
                    )
                team_name = cache.get(f'TEAM_{room_id}')
                if team_name is not None:
                    for team in team_name:
                        _team = team.replace(" ", "")
                        async_to_sync(self.channel_layer.group_send)(
                                'operator_team_{}_{}'.format(owner_id, str(_team)),
                                {

                                    **text_data_json,
                                    'type': 'chat_message',
                                }
                            )
                else:        
                    async_to_sync(self.channel_layer.group_send)(
                        str(self.operator_id),
                        {
                            **text_data_json,
                            'type': 'chat_message',
                        }
                    )

                if user == "operator":
                    try:
                        if self.bot_type is None:
                            pass
                        elif self.bot_type in ['whatsapp', 'facebook']:
                            if 'message' in text_data_json:
                                if 'msg_type' in text_data_json and text_data_json['msg_type'] == 'media':
                                    send_admin_message(room_id, text_data_json['message'], self.bot_type, msg_type='media', enter_chat=True, api=True)
                                else:
                                    send_admin_message(room_id, text_data_json['message'], self.bot_type, enter_chat=True, api=False)
                            else:
                                print("No message in text_data_json")
                    except Exception as ex:
                        logger.info(f"{ex}")

                events.append_msg_to_redis(room_id, text_data_json, store_full=True)
                num_msgs = cache.get(f"CLIENTWIDGET_COUNT_{room_id}", 0)
                num_msgs += 1
                cache.set(f"CLIENTWIDGET_COUNT_{room_id}", num_msgs, timeout=lock_timeout + BUFFER_TIME)
            
            except Exception as ex:
                print(ex)
    

    def template_message(self, event):
        try:
            self.send(text_data=json.dumps(event))
        except Exception as ex:
            print(ex)
    
    # Livechat messages
    def chat_message(self, event):
        try:
            self.send(text_data=json.dumps(event))
        except Exception as ex:
            print(ex)

    @staticmethod
    def send_highlights(message, room_id, owner_id, time, secret=False):
        channel_layer = get_channel_layer()
        message = {
            "highlights": str(message),
            "room_id": str(room_id), 
            "secret": secret,
            "time": time
        }
        client_map = cache.get(f"CLIENT_MAP_{owner_id}")
        if client_map is not None and str(room_id) in client_map:
            operator_id = client_map[str(room_id)]
            for operator in operator_id:
                group_name = str(operator)
                async_to_sync(channel_layer.group_send)(
                    group_name,
                    {
                        'type': 'chat_message',
                        **message
                    }
                )
