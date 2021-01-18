import uuid
from datetime import datetime

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.apps import apps
from django.conf import settings
# from django.contrib.postgres.fields import JSONField
from django.core.cache import cache
from django.db import models
from django.utils import timezone
from django.utils.translation import ugettext_lazy as _
from django_jsonfield_backport.models import JSONField

from apps.accounts.models import Teams, User
from apps.chatbox.models import Chatbox
from .exceptions import logger

try:
    from apps.clientwidget_updated import tasks
except ImportError:
    from . import tasks


def chatroom_from_1000():
    """
    Returns the next default value for the `ones` field, starts from 1000
    """
    largest = ChatRoom.objects.all().order_by('id').last()
    if largest is None:
        return 1000
    return largest.ones + 1


def current_utc_time():
    return timezone.now()


class ChatSession(models.Model):
    """Model for storing session information for Clientwidget chats

    Attributes:
        id (int): Auto Incrementing Integer ID (Primary Key)
        room_id (uuid): Room Id to the ChatRoom relation
        room_name (str): Room Name
        session_token (str): A 64 bitstring for authenticating any session
        prev (str): The previous token
        updated_on (datetime): Latest time for the session update
        ip_address (str): The IP Address of the Anonymous User
    """
    id = models.AutoField(primary_key=True)
    room_id = models.UUIDField(default=uuid.uuid4, editable=False, db_column='room_id')
    session_token = models.CharField(max_length=64, db_column='session_token', null=True)
    prev = models.CharField(max_length=64, db_column='prev', null=True)
    updated_on = models.DateTimeField(auto_now_add=True, db_column='updated_on')
    ip_address = models.CharField(max_length=30, db_column='ip_address', null=True)


class ChatRoom(models.Model):
    """Model for storing the room information related to the template bot
       
    Attributes:
        uuid (uuid): Unique ID for a generated chat room
        created_on (datetime): Time of room creation
        current_state (str): Represents the current state of the bot (redundant)
        bot_id (uuid): Bot ID which maps to an existing bot from `apps.chatbox.models.Chatbox`
        bot_is_active (bool): Is the bot active or not?
        num_msgs (int): Total number of messages for the current room
    """
    visitor_id = models.PositiveIntegerField(default=1, db_column='visitor_id')
    room_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_column='room_id')
    created_on = models.DateTimeField(_('chatroom created on'), default=current_utc_time)
    room_name = models.CharField(max_length=1000, null=True)
    messages = JSONField(db_column='messages', default=list)
    variables = JSONField(db_column='variables', default=dict)
    bot_id = models.UUIDField(db_column='bot_id')
    chatbot_type = models.CharField(max_length=10, db_column='chatbot_type', default='website')
    bot_is_active = models.BooleanField(default=False, db_column='bot_is_active')
    num_msgs = models.PositiveIntegerField(default=0, db_column='num_msgs')
    is_lead = models.BooleanField(default=False, db_column='is_lead')
    STATUS_LIST = (
        ('pending', 'Pending'),
        ('resolve', 'Resolve'),
        ('abandoned', 'Abandoned'),
        ('private_note', 'Private Note'),
        ('critical', 'Critical')
        )
    status = models.CharField(max_length=25, choices=STATUS_LIST, default='pending', null=True, blank=True)
    takeover = models.BooleanField(default=False)
    end_time = models.DateTimeField(db_column='end_time', null=True)
    recent_messages = JSONField(db_column='recent_messages', default=list)
    admin_id = models.IntegerField(null=True, blank=True)
    utm_source = models.CharField(max_length=25, null=True, blank=True)
    utm_medium = models.CharField(max_length=25, null=True, blank=True)
    utm_campaign = models.CharField(max_length=25, null=True, blank=True)
    utm_term = models.CharField(max_length=25, null=True, blank=True)
    utm_content = models.CharField(max_length=25, null=True, blank=True)
    website_url = models.URLField(max_length=255, blank=True, db_column="website_url")
    channel_id = models.CharField(max_length=255, blank=True, db_column="channel_id")
    ASSIGNMENT_TYPE = (
        ('', 'NONE'),
        ('automatic', 'Automatic'),
        ('manual', 'Manual'),
    )
    assignment_type = models.CharField(max_length=10, choices=ASSIGNMENT_TYPE, default='', null=True)
    assigned_operator = models.EmailField(_('email address'), null=True, blank=True)
    team_assignment_type = models.CharField(max_length=10, choices=ASSIGNMENT_TYPE, default='', null=True)
    assigned_team = models.IntegerField(null=True, blank=True)
    end_chat = models.BooleanField(default=False)
    updated_on = models.DateTimeField(db_column='updated_on', null=True)

    def save(self, *args, **kwargs):
        if 'new_visitor' in kwargs:
            try:
                if kwargs['new_visitor'] == True:
                    if self._state.adding:
                        if 'using' in kwargs:
                            last_id = ChatRoom.objects.using(kwargs['using']).filter(admin_id=self.admin_id).aggregate(largest=models.Max('visitor_id'))
                            last_id = last_id['largest']
                        else:    
                            last_id = ChatRoom.objects.filter(admin_id=self.admin_id).aggregate(largest=models.Max('visitor_id'))
                            last_id = last_id['largest']
                        if last_id is not None:
                            self.visitor_id = last_id + 1
                            self.room_name = f"Visitor{self.visitor_id}"
                        else:
                            self.visitor_id = 1
                            self.room_name = f"Visitor{self.visitor_id}"
            except Exception as ex:
                print(ex)
            finally:
                del kwargs['new_visitor']
        
        if 'preview' in kwargs:
            try:
                if kwargs['preview'] == True:
                    self.channel_id = 'preview'
            finally:
                del kwargs['preview']
        
        if 'standalone' in kwargs:
            try:
                if kwargs['standalone'] == True:
                    self.channel_id = 'standalone page'
            finally:
                del kwargs['standalone']
        
        send_update = False

        if 'send_update' in kwargs and kwargs['send_update'] == True:
            print("SENDING UPDATE..........")
            del kwargs['send_update']
            send_update = True
        
        if 'all_team' in kwargs:
            all_team = kwargs['all_team']
            del kwargs['all_team']

        else:
            all_team = False
        if 'assigned_operator' in kwargs:
            assigned_operator = kwargs['assigned_operator']
            if len(assigned_operator) == 1:
                if hasattr(assigned_operator[0], 'email'):
                    self.assigned_operator = assigned_operator[0].email
                    # self.assigned_team_name = assigned_operator[0].team_member.name
                    # if 'is_team_assignment' in kwargs and kwargs['is_team_assignment'] == True:
                    #     self.assigned_team_name = self.assigned_operator.team_member.name
                    # del kwargs['is_team_assignment']
                    # else:    
                    self.assigned_team_name = None 
                    logger.info(f'operator_here---->{assigned_operator}')
            else:        
                self.assigned_team = assigned_operator.first().team_member.id
                if all_team:
                    self.assigned_team_name = '<All>'
                    self.assigned_operator = '<All>'
                else:    
                    self.assigned_team_name = assigned_operator.first().team_member.name
                    self.assigned_operator = assigned_operator.first().team_member.name
            del kwargs['assigned_operator']

        else:
            assigned_operator = None
            self.assigned_team_name = None
        
        if 'assignment_type' in kwargs:
            self.assignment_type = kwargs['assignment_type']
            del kwargs['assignment_type']

        if 'assigner' in kwargs:
            assigner = kwargs['assigner']
            del kwargs['assigner']
        else:
            assigner = None

        if 'one_to_one' in kwargs:
            one_to_one = True
            del  kwargs['one_to_one']
        else:
            one_to_one = False

        if 'operator_partner' in kwargs:
            operator_partner = kwargs['operator_partner']
            del kwargs['operator_partner']
        else:
            operator_partner = False        
        
        super(ChatRoom, self).save(*args, **kwargs)

        if send_update:
            fields = ('bot_id', 'room_id', 'room_name', 'created_on', 'updated_on', 'bot_is_active', 'variables', 'status', 'takeover', 'assignment_type', 'assigned_operator',)
            if hasattr(settings, 'CELERY_TASK') and settings.CELERY_TASK == True:
                # Use Celery
                try:
                    
                    user = User.objects.get(pk=self.admin_id)
                    owner_id = user.uuidassigned_operator_id
                    bot = Chatbox.objects.get(pk=self.bot_id)
                    if owner_id is not None:
                        field_dict = {field: getattr(self, field) if field not in ('room_id', 'bot_id', 'created_on', 'updated_on') else str(getattr(self, field)) for field in fields}
                        field_dict['bot_type'] = bot.chatbot_type
                        field_dict['is_deleted'] = bot.is_deleted
                        field_dict['owner'] = bot.owner.email
                        if self.assigned_team_name == '<All>':
                            team_list_queryset = Teams.objects.filter(owner__id=self.admin_id).values_list('name', flat=True)
                            # team_list = list(map(str, team_list_queryset))
                            team_list = []
                            for team in team_list_queryset:
                                team_list.append(str(team))
                        else:
                            team_list = [self.assigned_team_name]

                        _ = tasks.send_update.delay(str(owner_id), field_dict, team_name=team_list)

                except Exception as ex:
                    print(ex)
            else:
                # Status has changed. This is an update
                try:
                    channel_layer = get_channel_layer()
                    user = User.objects.get(pk=self.admin_id)
                    owner_id = user.uuid
                    print('OWNER_ID', owner_id)
                    bot = Chatbox.objects.get(pk=self.bot_id)
                    if owner_id is not None:
                        field_dict = {field: getattr(self, field) if field not in ('room_id', 'bot_id', 'created_on', 'updated_on') else str(getattr(self, field)) for field in fields}
                        # Add bot_info
                        field_dict['bot_type'] = bot.chatbot_type
                        field_dict['is_deleted'] = bot.is_deleted
                        field_dict['owner'] = bot.owner.email

                        if assigned_operator is not None:
                            # Update operator <-> owner mappings
                            if self.room_id is not None and self.status is not None:
                                assigned_team_op = [str(op_uuid.uuid) for op_uuid in assigned_operator]
                                if self.assigned_team_name is not None:
                                    previous_team = cache.get(f'TEAM_{self.room_id}')
                                    logger.info(f'Previous Team---->{previous_team}')
                                    if previous_team is not None:
                                        dummy_fields = field_dict.copy()
                                        dummy_fields['bot_is_active'] = False
                                        for team in previous_team:
                                            _team = team.replace(" ", "")
                                            async_to_sync(channel_layer.group_send)(
                                                'team_{}_{}'.format(owner_id, str(_team)),
                                                {
                                                    'type': 'listing_channel_event',
                                                    **dummy_fields,
                                                }
                                            )
                                    else:
                                        client = cache.get(f"CLIENT_MAP_{owner_id}")
                                        if client is not None and str(self.room_id) in client:
                                            operators = client[str(self.room_id)]
                                            dummy_fields = field_dict.copy()
                                            dummy_fields['bot_is_active'] = False
                                            for op in operators:
                                                async_to_sync(channel_layer.group_send)(
                                                f'listing_channel_{str(op)}',
                                                {
                                                        'type': 'listing_channel_event',
                                                        **dummy_fields
                                                } 
                                                )
                                    if self.assigned_team_name == '<All>':
                                    
                                        team_list_queryset = Teams.objects.filter(owner__id=self.admin_id).values_list('name', flat=True)
                                        # team_list = list(map(str, team_list_queryset))
                                        team_list = []
                                        for team in team_list_queryset:
                                            team_list.append(str(team))
                                    else:
                                        team_list = [self.assigned_team_name]
                                    tasks.update_operator_mappings(str(owner_id), assigned_team_op, str(self.room_id), self.status, team_list)
                                else:
                                    client = cache.get(f"CLIENT_MAP_{owner_id}")
                                    if client is not None and str(self.room_id) in client:
                                        operators = client[str(self.room_id)]
                                        dummy_fields = field_dict.copy()
                                        dummy_fields['bot_is_active'] = False
                                        for op in operators:
                                            async_to_sync(channel_layer.group_send)(
                                               f'listing_channel_{str(op)}',
                                               {
                                                    'type': 'listing_channel_event',
                                                    **dummy_fields
                                               } 
                                            )
                                        logger.info(f"checkout operator--->{client[str(self.room_id)]}")        
                                    tasks.update_operator_mappings(str(owner_id), assigned_team_op, str(self.room_id), self.status)
                        else:
                            pass
                        
                        async_to_sync(channel_layer.group_send)(
                            f'listing_channel_{owner_id}',
                            {
                                'type': 'listing_channel_event',
                                **field_dict
                            }
                        )
                        
                        client_map = cache.get(f"CLIENT_MAP_{owner_id}")
                        operator_team_name = cache.get(f"TEAM_{self.room_id}")
                        if client_map is not None and str(self.room_id) in client_map:
                            operator_id = client_map[str(self.room_id)]
                            
                            if assigner is not None and str(assigner.uuid) not in operator_id:
                                operator_id.append(str(assigner.uuid))
                            logger.info(f'operator_assignment--->team...{operator_team_name}')    
                            if operator_team_name is not None and not one_to_one:
                                logger.info(f'operator_assignment--->team...{operator_team_name}')
                                for team in operator_team_name:
                                    _team = team.replace(" ", "")
                                    async_to_sync(channel_layer.group_send)(
                                        'team_{}_{}'.format(owner_id, str(_team)),
                                        {
                                            'type': 'listing_channel_event',
                                            **field_dict,
                                        }
                                    )
                            else:
                                if len(operator_id) != 0:
                                    logger.info(f'operator_assignment--->operator')
                                    for operator in operator_id:
                                        async_to_sync(channel_layer.group_send)(
                                            'listing_channel_' + str(operator),
                                            {
                                                'type': 'listing_channel_event',
                                                **field_dict,
                                            }
                                        )    
                except Exception as ex:
                    print(ex)


# ClientMediaHandler
class ClientMediaHandler(models.Model):
    room_id = models.UUIDField()
    bot_id = models.UUIDField()
    CHATBOT_TYPE = (
	('website', 'WEBSITE'),
	('whatsapp', 'WHATSAPP'),
    ('facebook', 'FACEBOOK'),
    ('apichat', 'APICHAT'),
    )
    bot_type = models.CharField(choices=CHATBOT_TYPE, max_length=25, default='website')
    media_file = models.FileField(upload_to='client_media/', max_length=100, null=True)
    media_type = models.CharField(max_length=10, default='image')
    active = models.BooleanField(default=True)
    created = models.DateTimeField(auto_now_add=True)
    media_url = models.URLField(null=True)


# AdminMediaHandler
class AdminMediaHandler(models.Model):
    room_id = models.UUIDField()
    bot_id = models.UUIDField()
    CHATBOT_TYPE = (
	('website', 'WEBSITE'),
	('whatsapp', 'WHATSAPP'),
    ('facebook', 'FACEBOOK'),
    ('apichat', 'APICHAT'),
    )
    bot_type = models.CharField(choices=CHATBOT_TYPE, max_length=25, default='website')
    media_file = models.FileField(upload_to='admin_media/', max_length=100, null=True)
    media_type = models.CharField(max_length=10, default='image')
    active = models.BooleanField(default=True)
    created = models.DateTimeField(auto_now_add=True)
    media_url = models.URLField(null=True)
