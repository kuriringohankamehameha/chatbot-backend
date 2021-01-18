import copy
import json
import os
import uuid
from datetime import date, datetime, timedelta

import pytz
import requests
from decouple import config
from django.apps import apps
from django.conf import settings
from django.core.cache import cache
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from google.oauth2 import credentials
from googleapiclient.discovery import build
from pytz import country_timezones
from rest_framework import generics, permissions, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.chatbox.serializers import ChatboxListSerializer
from apps.clientwidget.events import get_variables
from apps.clientwidget.serializers import VariableDataSerializer

from . import serializers, utils

# from . import tasks

ChatRoom = apps.get_model(app_label='clientwidget', model_name='ChatRoom')
Chatbox = apps.get_model(app_label='chatbox', model_name='Chatbox')


class ChatbotListAPI(APIView):
    """API to list all the chatbots which have a chat history with users
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Returns a list of all the bots under the authenticated user which have a valid chat history
        """
        result = {}
        
        queryset = Chatbox.objects.using('default').filter(owner=self.request.user, is_deleted=False, bot_variable_json__isnull=False)
        
        if queryset.count() == 0:
            # No bots exist. Simply return empty dict
            return Response(result, status=status.HTTP_200_OK)
        
        for bot_obj in queryset:
            result[str(bot_obj.pk)] = {"title": bot_obj.title, "chatbot_type": bot_obj.chatbot_type}
        
        query = queryset.all()
        
        # Now filter based on having a valid chat history
        chatbox = []
        for q in queryset:
            chatbox.append(q.pk)
        filtered_query = ChatRoom.objects.using(request.user.ext_db_label).filter(bot_id__in=chatbox)

        for chatroom_obj in filtered_query:
            if chatroom_obj.variables is None:
                if str(chatroom_obj.bot_id) in result:
                    del result[str(chatroom_obj.bot_id)]

        return Response(result, status=status.HTTP_200_OK)


class ChatDataHeaderAPI(APIView):
    """API for dealing with the database column names for every unique bot.

    Endpoint URLs:
        1. api/chatdata/headers/<bot_id>
    """
    permission_classes = [IsAuthenticated]
    required_fields = serializers.ChatHeaderSerializer._required_fields

    def get(self, request, bot_id):
        """Fetches the Database Column names from the ChatRoom model for `bot_id`.

        Returns:
            HTTP_200_OK status code + column names on success. If `bot_id` is not found, it returns HTTP_404_NOT_FOUND, and a HTTP_400_BAD_REQUEST otherwise
        """
        # Get the column names from the field names
        columns = [field.get_attname_column()[1] for field in ChatRoom._meta.fields]

        # Now filter on the required fields
        required_fields = self.required_fields
        filtered_columns = list(filter(lambda field: field in required_fields, columns))

        if filtered_columns == []:
            return Response("Filtered Columns is Empty", status=status.HTTP_400_BAD_REQUEST)
        
        # Now fetch the variable names from the bot
        queryset = Chatbox.objects.filter(pk=bot_id, owner_id=request.user.pk)

        if queryset.count() == 0:
            return Response(status=status.HTTP_404_NOT_FOUND)
        
        instance = queryset.first()

        # We need to take into account the ENTIRE Unioned history of variables
        variables = {variable: "" for variable in instance.variable_columns}

        filtered_columns.append({'variables': variables})

        # Add bot_lead_json
        filtered_columns.append({'bot_lead_json': instance.bot_lead_json})
        
        return Response(filtered_columns, status=status.HTTP_200_OK)
    

    def post(self, request, bot_id):
        """POST Request to get the variable fields from the front-end
        """
        if 'headers' in request.data:
            if (not isinstance(request.data['headers'], list)):
                return Response("Request Payload must contain {\"headers\": [{field_name: col_name}, ..., {variable_name: col_name}, ...]}", status=status.HTTP_400_BAD_REQUEST)
            
            if request.data['headers'] == []:
                # Empty List
                # Reset it
                if f'chatdata_fields_{bot_id}' in request.session:
                    del request.session[f'chatdata_fields_{bot_id}']
                if f'chatdata_fields_{bot_id}' in request.session:
                    del request.session[f'chatdata_column_names_{bot_id}']
                return Response(status=status.HTTP_200_OK)
            
            field_map = request.data['headers']

            try:
                fields = list(list(field.items())[0][0] if field is not None else None for field in field_map)
                column_names = list(list(field.items())[0][1] if field is not None else None for field in field_map)
            except:
                return Response("Only one null object allowed. Request Payload must contain {\"headers\": [{field_name: col_name}, ..., {variable_name: col_name}, ...]}", status=status.HTTP_400_BAD_REQUEST)
            
            # Store the headers in the session
            # We need to retrieve it later during the export API
            request.session[f'chatdata_fields_{bot_id}'] = fields
            request.session[f'chatdata_column_names_{bot_id}'] = column_names
            return Response(status=status.HTTP_200_OK)
        else:
            if f'chatdata_fields_{bot_id}' in request.session:
                del request.session[f'chatdata_fields_{bot_id}']
            if f'chatdata_fields_{bot_id}' in request.session:
                del request.session[f'chatdata_column_names_{bot_id}']

            return Response("Set the column names as the DB columns (Default)", status=status.HTTP_200_OK)


class ChatDataGlobalAPI(APIView):
    """API which lists the chatbots globally. It can list all the chatbots for a given user, and can also list every single bot.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, chat_type):
        if chat_type not in ('global', 'user'):
            return Response("chat_type can only be \"global\" or \"user\"", status=status.HTTP_400_BAD_REQUEST)
        
        if chat_type == 'global':
            # Every single bot
            queryset = ChatRoom.using(request.user.ext_db_label).objects.all()
            serializer = VariableDataSerializer(queryset, many=True, context={'utc_offset': request.user.utc_offset})
            return Response(serializer.data, status=status.HTTP_200_OK)
        
        elif chat_type == 'user':
            # All bots for that user
            queryset = ChatRoom.objects.using(request.user.ext_db_label).filter(admin_id=request.user.id)
            serializer = VariableDataSerializer(queryset, many=True, context={'utc_offset': request.user.utc_offset})
            return Response(serializer.data, status=status.HTTP_200_OK)
        
        return Response(status=status.HTTP_200_OK)


class ChatDataBotAPI(APIView):
    """API for dealing with the Chat Data for a given bot.

    Endpoint URLs:
        1. api/chatdata/bot/<bot_id>
    """
    permission_classes = [IsAuthenticated]

    def get_room_variable_data(self, owner, room_id: uuid.UUID) -> dict:
        """Fetches the variable data for a particular `room_id`

        Returns:
            A `dict` of the form `{"@name": "xyz", "@email": "xyz@mail"}` on success, and `None` on failure
        """
        room_object = ChatRoom.objects.using(owner.user.ext_db_label).get(pk=room_id)
        queryset = ChatRoom.objects.using(owner.ext_db_label).filter(room_id=room_object.room_id)
        if queryset.count() == 0:
            # Empty Chat History. Return dict()
            return dict()
        else:
            instance = queryset.first()
            return instance.variables
    

    def get_bot_variable_data(self, bot_id: uuid.UUID) -> dict:
        """Fetches the variable data for all chats corresponding to a bot with id `bot_id`

        Args:
            bot_id (uuid.UUID): UUID representing the hash id of the Chatbot

        Raises:
            Http404: If the `bot_id` doesn't exist

        Returns:
            dict: A dictionary containing the variable data for that chat
        """
        bot = Chatbox.objects.get(bot_hash=bot_id)
        queryset = ChatRoom.objects.using(bot.owner.ext_db_label).filter(bot_id=bot_id)
        if queryset.count() == 0:
            raise Http404
        else:
            instance = queryset.objects.first()
            room_id = instance.pk
            return self.get_room_variable_data(bot.owner, room_id)
        

    def get(self, request, bot_id):
        """Fetches the Variable data fields for all the chats of that particular bot.

        Returns:
            1. HTTP_200_OK status code + content on success.
            2. HTTP_404_NOT_FOUND if the bot doesn't exist.
            3. HTTP_204_NO_CONTENT if the bot has no chat history.
        """
        queryset = Chatbox.objects.filter(pk=bot_id, owner_id=request.user.pk)
        if queryset.count() == 0:
            return Response("Invalid bot_id. No such bot exists", status=status.HTTP_404_NOT_FOUND)
        instance = queryset.first()
        queryset = ChatRoom.objects.using(instance.owner.ext_db_label).filter(bot_id=bot_id)
        if queryset.count() == 0:
            return Response([], status=status.HTTP_204_NO_CONTENT)
            #return Response("No chat history exists for this bot", status=status.HTTP_400_BAD_REQUEST)
        
        if 'field' not in request.query_params:
            field = 'created_on'
            fields = ['-updated_on', '-created_on']
        else:
            field = request.query_params['field']
            fields = None
            columns = [field.get_attname_column()[1] for field in ChatRoom._meta.fields]
            if field not in columns:
                return Response(f"Invalid field: {field}", status=status.HTTP_400_BAD_REQUEST)
        
        if 'order' not in request.query_params:
            # Descending Order
            if fields is not None:
                for field in fields:
                    queryset = queryset.order_by(field)
            else:
                queryset = queryset.order_by(f'-{field}')
        else:
            order = request.query_params
            if order not in ['asc', 'desc']:
                return Response(f"Order can only be asc / desc", status=status.HTTP_400_BAD_REQUEST)
            if order == 'asc':
                queryset = queryset.order_by(f'{field}')
            else:
                queryset = queryset.order_by(f'-{field}')
        
        serializer = VariableDataSerializer(queryset, many=True, context={'utc_offset': request.user.utc_offset})
        return Response(serializer.data, status=status.HTTP_200_OK)


class ChatDataRoomAPI(APIView):
    """API for dealing with the Chat Data for a given room.

    Endpoint URLs:
        1. api/chatdata/room/<room_name>
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, room_name):
        """Fetches the Variable data for a particular room_name

        Returns:
            HTTP_200_OK status code + content on success, and a HTTP_404_NOT_FOUND if the bot doesn't exist.
        """
        queryset = ChatRoom.objects.using(request.user.ext_db_label).filter(room_name=room_name)
        if queryset.count() == 0:
            return Response(status=status.HTTP_404_NOT_FOUND)
        instance = queryset.first()
        serializer = VariableDataSerializer(instance)
        return Response(serializer.data, status=status.HTTP_200_OK)


class ChatDataCountLeads(APIView):
    """API for displaying the number of leads for that bot
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, bot_id: uuid.UUID, start_date=None, end_date=None):        
        queryset = ChatRoom.objects.using(request.user.ext_db_label).filter(bot_id=bot_id, is_lead=True)
        
        if start_date is None and end_date is None:
            pass
        else:
            if end_date is None or end_date == "null":
                d = timezone.now().date()
                end_date = datetime(d.year, d.month, d.day)
                try:
                    start_date = datetime.strptime(start_date, "%Y-%m-%d")
                except:
                    return Response("Invalid Date Format: Must be yyyy-mm-dd", status=status.HTTP_400_BAD_REQUEST)
            else:
                try:
                    start_date = datetime.strptime(start_date, "%Y-%m-%d")
                    end_date = datetime.strptime(end_date, "%Y-%m-%d")
                except:
                    return Response("Invalid Date Format: Must be yyyy-mm-dd", status=status.HTTP_400_BAD_REQUEST)

            start_date = start_date - timedelta(minutes=request.user.utc_offset)
            end_date = end_date - timedelta(minutes=request.user.utc_offset)
            
            queryset = queryset.filter(created_on__range=[start_date, end_date + timedelta(days=1)])
        
        return Response(queryset.count(), status=status.HTTP_200_OK)


class ChatDataCountVisitors(APIView):
    """API for displaying the number of visitors for that bot
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, bot_id: uuid.UUID, start_date=None, end_date=None):
        queryset = ChatRoom.objects.using(request.user.ext_db_label).filter(bot_id=bot_id)

        if start_date is None and end_date is None:
            pass
        else:
            if end_date is None or end_date == "null":
                d = timezone.now().date()
                end_date = datetime(d.year, d.month, d.day)
                try:
                    start_date = datetime.strptime(start_date, "%Y-%m-%d")
                except:
                    return Response("Invalid Date Format: Must be yyyy-mm-dd", status=status.HTTP_400_BAD_REQUEST)
            else:
                try:
                    start_date = datetime.strptime(start_date, "%Y-%m-%d")
                    end_date = datetime.strptime(end_date, "%Y-%m-%d")
                except:
                    return Response("Invalid Date Format: Must be yyyy-mm-dd", status=status.HTTP_400_BAD_REQUEST)

            start_date = start_date - timedelta(minutes=request.user.utc_offset)
            end_date = end_date - timedelta(minutes=request.user.utc_offset)
            
            queryset = queryset.filter(created_on__range=[start_date, end_date + timedelta(days=1)])

        return Response(queryset.count(), status=status.HTTP_200_OK)


class ChatDataSortAPI(APIView):
    """API for Sorting the Chat Data based on paramters.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, bot_id: uuid.UUID, field: str=None, order: str=None, start_date: str=None, end_date: str=None, is_lead: str=None):
        """Sorts the Chat data for `bot_id` based on `field`

        Args:
            bot_id (uuid.UUID): The ID of an existing bot
            field (str): The name of the field to sort
            order (str): Whether to specify an 'asc' or 'desc' order
            start_date (str): The starting date for filter (YYYY-MM-DD)
            end_date (str): The end date for filter (YYYY-MM-DD)
            is_lead (bool): To filter for lead based chats
        """
        if order is None or order == '':
            order = 'desc'
        elif order not in ('asc', 'desc'):
            return Response("Order must be between one of (asc, desc)", status=status.HTTP_400_BAD_REQUEST)
        
        queryset = ChatRoom.objects.using(request.user.ext_db_label).filter(bot_id=bot_id)
        if queryset.count() == 0:
            return Response([], status=status.HTTP_204_NO_CONTENT)
        
        if is_lead is None:
            pass
        else:
            if is_lead in ('true', 'True'):
                is_lead = True
            elif is_lead in ('false', 'False'):
                is_lead = False
            else:
                return Response("is_lead must be between one of (true, false)", status=status.HTTP_400_BAD_REQUEST)
            queryset = queryset.filter(is_lead=is_lead)
        if start_date is None and end_date is None:
            pass
        else:
            if end_date is None or end_date == "null":
                d = timezone.now().date()
                end_date = datetime(d.year, d.month, d.day)
                try:
                    start_date = datetime.strptime(start_date, "%Y-%m-%d")
                except:
                    return Response("Invalid Date Format: Must be yyyy-mm-dd", status=status.HTTP_400_BAD_REQUEST)
            else:
                try:
                    start_date = datetime.strptime(start_date, "%Y-%m-%d")
                    end_date = datetime.strptime(end_date, "%Y-%m-%d")
                except:
                    return Response("Invalid Date Format: Must be yyyy-mm-dd", status=status.HTTP_400_BAD_REQUEST)

            start_date = start_date - timedelta(minutes=request.user.utc_offset)
            end_date = end_date - timedelta(minutes=request.user.utc_offset)
            
            queryset = queryset.filter(created_on__range=[start_date, end_date + timedelta(days=1)])
                
        if field is not None:
            if field in ('Date', 'date'):
                field = 'created_on'
            
            columns = [field.get_attname_column()[1] for field in ChatRoom._meta.fields]

            if field not in columns:
                return Response("Sort API: Invalid field - {field}", status=status.HTTP_404_NOT_FOUND)
        else:
            field = 'created_on'
            fields = ['-updated_on', '-created_on']
            if order == 'asc':
                # Ascending Order
                queryset = queryset.order_by(field)
            else:
                if fields is not None:
                    for field in fields:
                        queryset = queryset.order_by(field)
                else:
                    # Descending Order
                    queryset = queryset.order_by(f'-{field}')

        serializer = VariableDataSerializer(queryset, many=True, context={'utc_offset': request.user.utc_offset})
        return Response(serializer.data, status=status.HTTP_200_OK)


class ExportBotChatDataAPI(APIView):
    """API for exporting a Bot's Chat data into CSV / XLSX format.
    """
    permission_classes = [IsAuthenticated]
    
    columns = ['visitor_id', 'room_name', 'created_on', 'updated_on', 'end_time', 'channel_id'] # Lead Fields
    
    #columns = [field.get_attname_column()[1] for field in ChatRoom._meta.fields if field.get_attname_column()[1] not in ['room_id', 'variables', 'bot_info', 'recent_messages', 'messages', 'bot_id', 'assignment_type', 'num_msgs']]

    format_types = set(['csv', 'xlsx'])

    def get(self, request, bot_id=None, fmt=None, chat_type=None):
        """Sends the chat data for a bot with ID `bot_id` in a particular format

        Args:
            bot_id (uuid.UUID): The ID of an existing bot
            fmt (str): The format of the exported file (csv / xlsx / pdf). Defaults to csv
        """
        if fmt is None:
            # Default is csv
            fmt = 'csv'
        if fmt not in self.format_types:
            return Response(f"Invalid Format. Accepted formats are {self.format_types}", status=status.HTTP_400_BAD_REQUEST)
        
        export_only_lead_fields = True

        query_params = request.query_params

        start_date = query_params.get('start_date')
        end_date = query_params.get('end_date')

        filters = {}
        
        if start_date is None and end_date is None:
            pass
        else:
            if end_date is None or end_date == "null":
                d = timezone.now().date()
                end_date = datetime(d.year, d.month, d.day)
                try:
                    start_date = datetime.strptime(start_date, "%Y-%m-%d")
                except:
                    return Response("Invalid Date Format: Must be yyyy-mm-dd", status=status.HTTP_400_BAD_REQUEST)
            else:
                try:
                    start_date = datetime.strptime(start_date, "%Y-%m-%d")
                    end_date = datetime.strptime(end_date, "%Y-%m-%d")
                except:
                    return Response("Invalid Date Format: Must be yyyy-mm-dd", status=status.HTTP_400_BAD_REQUEST)

            start_date = start_date - timedelta(minutes=request.user.utc_offset)
            end_date = end_date - timedelta(minutes=request.user.utc_offset)

            filters['start_date'] = start_date
            filters['end_date'] = end_date + timedelta(days=1)
        
        if bot_id is not None:
            # Get the headers
            queryset = Chatbox.objects.filter(pk=bot_id, owner_id=request.user.pk)
            if queryset.count() == 0:
                return Response(f"No Bot with bot-id {bot_id}", status=status.HTTP_400_BAD_REQUEST)
            
            instance = queryset.first()
            variable_json = instance.bot_variable_json
            lead_json = instance.bot_lead_json
            
            if variable_json is None:
                return Response(f"Bot with id {bot_id} has a NULL variable_json field", status=status.HTTP_400_BAD_REQUEST)
            
            if lead_json is None:
                return Response(f"Bot with id {bot_id} has a NULL lead_json field", status=status.HTTP_400_BAD_REQUEST)

            variable_names = instance.variable_columns

            if variable_names is None:
                # Fallback option
                variable_names = list(variable_json.keys())
            
            lead_names = list(lead_json.keys())

            # Keep a separator between the variable columns and the other fields
            # We need this to identify whether a column is a variable field or not
            separator = [None]

            if export_only_lead_fields == False:
                self.columns = variable_names + separator + self.columns
            else:
                self.columns = lead_names + separator + self.columns

            if hasattr(settings, 'USE_CELERY') and settings.USE_CELERY == True:
                # _ = tasks.export_chat_data_task.delay(request, bot_id=bot_id, fields=self.columns, fmt=fmt)
                return Response("Download Started", status=status.HTTP_200_OK)
            else:
                return utils.export_chat_data(request, bot_id=bot_id, fields=self.columns, fmt=fmt, send_email=False, fetch_leads=False, export_only_lead_fields=export_only_lead_fields, filters=filters)
        else:
            if chat_type is None or chat_type not in ('global', 'user'):
                return Response("Neet to specify chat_type (global / user)", status=status.HTTP_400_BAD_REQUEST)
            else:
                return utils.export_chat_data(request, bot_id=chat_type, fields=self.columns, fmt=fmt, send_email=False, fetch_leads=False, export_only_lead_fields=export_only_lead_fields, filters=filters)


class SendChatDataEmailAPI(APIView):
    """API to send the Chatdata via an Email. This email will send it as an attachment
    """

    permission_classes = [IsAuthenticated]

    columns = ['visitor_id', 'room_name', 'created_on', 'updated_on', 'end_time', 'channel_id']
    # columns = [field.get_attname_column()[1] for field in ChatRoom._meta.fields if field.get_attname_column()[1] not in ['room_id', 'variables', 'bot_info', 'recent_messages', 'messages', 'bot_id', 'assignment_type']]
    
    format_types = set(['csv', 'xlsx'])

    def post(self, request, bot_id=None, fmt=None):
        if fmt is None:
            # Default is csv
            fmt = 'csv'
        
        if fmt not in self.format_types:
            return Response(f"Invalid Format. Accepted formats are {self.format_types}", status=status.HTTP_400_BAD_REQUEST)
        
        export_only_lead_fields = True
        
        if 'leads' in request.data and request.data['leads'] == True:
            # Only fetch leads
            fetch_leads = True
        else:
            fetch_leads = False
        
        fetch_leads = True

        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')

        filters = {}
        
        if start_date is None and end_date is None:
            pass
        else:
            if end_date is None or end_date == "null":
                d = timezone.now().date()
                end_date = datetime(d.year, d.month, d.day)
                try:
                    start_date = datetime.strptime(start_date, "%Y-%m-%d")
                except:
                    return Response("Invalid Date Format: Must be yyyy-mm-dd", status=status.HTTP_400_BAD_REQUEST)
            else:
                try:
                    start_date = datetime.strptime(start_date, "%Y-%m-%d")
                    end_date = datetime.strptime(end_date, "%Y-%m-%d")
                except:
                    return Response("Invalid Date Format: Must be yyyy-mm-dd", status=status.HTTP_400_BAD_REQUEST)

            start_date = start_date - timedelta(minutes=request.user.utc_offset)
            end_date = end_date - timedelta(minutes=request.user.utc_offset)

            filters['start_date'] = start_date
            filters['end_date'] = end_date + timedelta(days=1)

        
        if bot_id is not None:
            return utils.export_chat_data(request, bot_id=bot_id, fields=self.columns, fmt=fmt, send_email=True, fetch_leads=False, export_only_lead_fields=export_only_lead_fields, filters=filters)
        else:
            if 'all_bots' in request.data and request.data['all_bots'] == True:
                # Send the data for every single bot
                return utils.export_chat_data(request, bot_id='global', fields=self.columns, fmt=fmt, send_email=True, fetch_leads=False, export_only_lead_fields=export_only_lead_fields, filters=filters)
            else:
                # Send all the bots for this user
                return utils.export_chat_data(request, bot_id='user', fields=self.columns, fmt=fmt, send_email=True, fetch_leads=False, export_only_lead_fields=export_only_lead_fields, filters=filters)

        return Response("Invalid Option", status=status.HTTP_400_BAD_REQUEST)


class UpdateLeadsAPI(APIView):
    """API for updating the `is_lead` flag for existing chats based on filters
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        for instance in ChatRoom.objects.using(request.user.ext_db_label).all():
            variables = instance.variables
            if '@email' in variables:
                if variables['@email'] not in ('', None):
                    if instance.is_lead == False:
                        instance.is_lead = True
                        instance.save()
            if '@phone' in variables:
                if variables['@phone'] not in ('', None):
                    if instance.is_lead == False:
                        instance.is_lead = True
                        instance.save()
        return Response("Updated leads", status=status.HTTP_200_OK)

class ExportToGsheets(APIView):
    permission_classes = (IsAuthenticated,)
    
    creds = None

    def post(self, request, bot_id):
        try:
            chatbot = Chatbox.objects.get(pk=bot_id, owner_id=request.user.pk)
            owner = chatbot.owner
        except Chatbox.DoesNotExist:
            raise Http404

        export_only_lead_fields = True

        serializer = serializers.GsheetTokenSerializer(data=request.data)
        bot_list = Chatbox.objects.get(bot_hash=bot_id, owner_id=request.user.pk)
        queryset = ChatRoom.objects.using(bot_list.owner.ext_db_label).filter(bot_id=bot_id).order_by('-created_on')
        
        if queryset.count() == 0:
            return Response([], status=status.HTTP_200_OK)

        fields = [field.get_attname_column()[1] for field in ChatRoom._meta.fields if field.get_attname_column()[1] not in ['room_id', 'variables', 'bot_info', 'recent_messages', 'messages', 'bot_id', 'assignment_type', 'num_msgs']]

        if f'chatdata_fields_{bot_id}' in request.session and f'chatdata_column_names_{bot_id}' in request.session:
            fields, column_names = request.session[f'chatdata_fields_{bot_id}'], request.session[f'chatdata_column_names_{bot_id}']
        else:
            lead_fields = ['visitor_id', 'room_name', 'created_on', 'updated_on', 'end_time', 'channel_id']
            column_names = None

        variable_json = chatbot.bot_variable_json
        lead_json = chatbot.bot_lead_json
        variable_names = chatbot.variable_columns

        query_params = request.query_params

        start_date = query_params.get('start_date')
        end_date = query_params.get('end_date')
        
        if start_date is None and end_date is None:
            pass
        else:
            if end_date is None or end_date == "null":
                d = timezone.now().date()
                end_date = datetime(d.year, d.month, d.day)
                try:
                    start_date = datetime.strptime(start_date, "%Y-%m-%d")
                except:
                    return Response("Invalid Date Format: Must be yyyy-mm-dd", status=status.HTTP_400_BAD_REQUEST)
            else:
                try:
                    start_date = datetime.strptime(start_date, "%Y-%m-%d")
                    end_date = datetime.strptime(end_date, "%Y-%m-%d")
                except:
                    return Response("Invalid Date Format: Must be yyyy-mm-dd", status=status.HTTP_400_BAD_REQUEST)

            start_date = start_date - timedelta(minutes=request.user.utc_offset)
            end_date = end_date - timedelta(minutes=request.user.utc_offset) + timedelta(days=1)
            queryset = queryset.filter(created_on__range=[start_date, end_date])

        if variable_names is None or export_only_lead_fields == True:
            # Fallback option
            if variable_json is None:
                variable_names = []
            else:
                if export_only_lead_fields == True:
                    if isinstance(lead_json, dict):
                        variable_names = list(lead_json.keys())
                    else:
                        variable_names = []
                else:
                    if isinstance(variable_json, dict):
                        variable_names = list(variable_json.keys())
                    else:
                        variable_names = []

        if column_names is None:
            fields = variable_names + lead_fields
            column_names = fields

        values = []
        values.append(column_names) # Headers

        for obj in queryset:
            row = []
            try:
                for field in fields:
                    attribute = None
                    if field is None:
                        continue
                    elif hasattr(obj, field):
                        attribute = getattr(obj, field)
                    else:
                        # Probably a variable
                        variables = getattr(obj, 'variables')
                        if field in variables:
                            attribute = variables[field]
                        else:
                            # This variable doesn't exist. Keep it as empty
                            attribute = ""
                    
                    if attribute is None:
                        attribute = ""
                    
                    if isinstance(attribute, datetime) or (field in ['created_on', 'updated_on', 'end_time']):
                        # datetime object cannot be JSON serializaed
                        attribute = str(timezone.template_localtime(attribute) + timedelta(minutes=owner.utc_offset))
                    elif isinstance(attribute, uuid.UUID):
                        attribute = str(attribute)
                    elif isinstance(attribute, str):
                        # Don't serialize strings
                        pass
                    else:
                        # Others can be JSON serialized
                        attribute = json.dumps(attribute)
                    #print(f"field = {field}, attribute = {attribute}")
                    try:
                        row.append(attribute)
                    except Exception as e:
                        print(e)
                        pass
            except Exception as ex:
                print(ex)
            values.append(row)

        body = {
            'values':values
        }
        
        if serializer.is_valid(raise_exception=True):
            
            spreadsheet = {
                'properties': {
                    'title': chatbot.title + str(timezone.now() + timedelta(minutes=owner.utc_offset))
                }
            }
            try:


                creds = credentials.Credentials(serializer.data['token'])
                service = build('sheets', 'v4', credentials=creds)
                request = service.spreadsheets().create(body=spreadsheet)
                response = request.execute()
                spreadsheet_id=response.get('spreadsheetId')
                chatbot.spreadsheetId = spreadsheet_id
                chatbot.save()
                request = service.spreadsheets().values().append(
                    spreadsheetId=spreadsheet_id,
                    range='sheet1',
                    valueInputOption='RAW',
                    body=body
                    )
                response = request.execute()
                print(f'Chatbot{bot_id} --> {spreadsheet_id}')
                
                print(response)
                
            except Exception as ex:
                print(ex)

            return Response(serializer.data, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
