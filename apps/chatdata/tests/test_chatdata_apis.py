import csv
import glob
import io
import itertools
import json
import os
import random
import string
import time
import uuid
from importlib import import_module
from typing import Callable, Iterator, List, Tuple

import pytest
import xlrd
from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.sessions import SessionMiddlewareStack
from channels.testing import WebsocketCommunicator
from django.apps import apps
from django.conf import settings
from django.contrib import auth
from django.contrib.auth.models import AnonymousUser
from django.core import mail, management
from django.urls import re_path
from mixer.backend.django import mixer
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.clientwidget.consumers import TemplateChatConsumer
from apps.clientwidget.models import ChatRoom


class TestChatDataApis:
    """Class for Testing all APIs related to the `chatdata` app
    """

    # Number of users to create
    num_users = 1
    rooms_per_user = 2


    @pytest.mark.django_db
    @pytest.mark.parametrize('setup_db_chatdata', [{'num_users': num_users, 'rooms_per_user': rooms_per_user}], indirect=True)
    def test_chatdata_api(self, client: APIClient, setup_db_chatdata: pytest.fixture) -> None:
        """Method to initiate and test the chatdata API

        Args:
            client (APIClient): The APIClient instance
            setup_db_chatdata (pytest.fixture): The `setup_db_chatdata()` fixture, which sets up the DB
        """
        # Now let's test it for the other users which have a bot
        # We'll get them from our `populate_db` setup fixture
        users, bots, variables, rooms_users, users_inputs = setup_db_chatdata

        assert len(users) == self.num_users and len(rooms_users) == self.num_users

        if len(rooms_users) > 0:
            assert len(rooms_users[0]) == self.rooms_per_user

        for (user, bot_id, variable_json, rooms, user_inputs) in zip(users, bots, variables, rooms_users, users_inputs):
            client.login(username=user, password='test')
            user = auth.get_user(client) # type: ignore
            assert user.is_authenticated

            response = client.get('/api/chatbox')
            assert response.status_code == 200

            data = json.loads(response.content)
            # Has already created a bot during the setup
            assert len(data) == 1 and data[0]['bot_hash'] == bot_id

            response = client.get('/api/chatdata/listing')
            listing = json.loads(response.content)
            assert bot_id in listing

            # Chatdata Headers
            response = client.get(f'/api/chatdata/headers/{bot_id}')
            data = json.loads(response.content)
            headers = set(field for field in data if not isinstance(field, dict))

            for obj in data:
                if isinstance(obj, dict) and 'variables' in obj:
                    headers.update(variable for variable in obj['variables'])

            fields = set({"room_id", "created_on", "room_name", "bot_id", "bot_is_active", "is_lead"}) # The required fields
            fields.update(set(var for var in variable_json)) # Add the variable names to the fields

            # Fields must be the same as the response headers
            assert fields == headers

            # Get the Chatdata
            response = client.get(f'/api/chatdata/bot/{bot_id}')
            data = json.loads(response.content)

            assert len(data) == len(rooms)

            # Sort the data according to room_name
            data = sorted(data, key=lambda item: item['room_name'])
            rooms = sorted(rooms)

            for row, room_name in zip(data, rooms):
                assert row['room_name'] == room_name
                assert row['variables'] in user_inputs
                assert 'messages' not in row


    @pytest.mark.django_db
    def test_chatdata_dummy_api(self, client: APIClient, setup_dummy_bots: pytest.fixture) -> None:
        """Method to initiate and test the chatdata API for incorrect bots

        Args:
            client (APIClient): The APIClient instance
            setup_dummy_bots (pytest.fixture): The `setup_dummy_bots()` fixture, which sets up the DB
        """
        user, bots, variables = setup_dummy_bots

        assert len(variables) == len(bots)

        client.login(username=user, password='test')

        response = client.get("/api/chatdata/listing")
        assert response.status_code == 200

        listing_data = json.loads(response.content)
        
        for bot_map, variable in zip(bots, variables):
            bot_hash, bot_name = list(bot_map.items())[0]
            
            if bot_name == "Test Empty Bot":
                assert variable in ({}, None)
                assert bot_hash not in listing_data
                response = client.get(f"/api/clientwidget/session/{bot_hash}")
                assert response.status_code == 404

                response = client.get(f"/api/chatdata/bot/{bot_hash}")
                assert response.status_code == 204
            
            elif bot_name == "Test Useless Bot":
                assert variable != {} or variable is not None
                # Even if it's variable data is {}, it must still show up
                assert bot_hash in listing_data

                queryset = ChatRoom.objects.filter(room_name=bot_name, bot_id=uuid.UUID(bot_hash))
                assert queryset.count() == 1

                instance = queryset.first()
                assert instance.room_name == bot_name and instance.variables == {} and instance.messages == []

                response = client.get(f"/api/chatdata/bot/{bot_hash}")
                assert response.status_code == 200
                
                data = json.loads(response.content)
                assert isinstance(data, list)

                for d in data:
                    assert 'variables' in d and isinstance(d['variables'], dict)
                    assert d['variables'] == {}

            else:
                assert bot_hash in listing_data and bot_name == listing_data[bot_hash]

                response = client.get(f"/api/clientwidget/session/{bot_hash}")
                assert response.status_code == 200

                data = json.loads(response.content)
                room_name = data['room_name']

                queryset = ChatRoom.objects.filter(room_name=room_name, bot_id=uuid.UUID(bot_hash))
                assert queryset.count() == 1

                instance = queryset.first()
                assert instance.room_name == room_name and instance.variables == {} and instance.messages == []


        client.logout()
    

    @pytest.mark.django_db
    def test_export_data(self, client: APIClient, setup_chatdata: pytest.fixture) -> None:
        user, bots, variables, rooms = setup_chatdata

        client.login(username=user, password='test')

        for bot_map in bots:
            bot_hash, bot_name = list(bot_map.items())[0]
            if bot_name == "Test Bot":
                response = client.get(f"/api/chatdata/bot/{bot_hash}")
                assert response.status_code == 200
                
                data = json.loads(response.content)
                assert len(data) == 10 # 10 Chats

                # Export the data now
                response = client.get(f"/api/chatdata/export/bot/{bot_hash}/csv")
                assert response.status_code == 200

                # Deal with the exported csv data
                content = response.content.decode('utf-8')
                csv_reader = csv.reader(io.StringIO(content))

                # Segregate the body and the headers
                body = list(csv_reader)
                headers = body.pop(0)

                reqd_fields = ["room_id", "created_on", "room_name", "messages", "bot_id", "chatbot_type", "bot_is_active", "is_lead", "status"]
                variable_fields = list(variables[0].keys())

                fields = reqd_fields + variable_fields

                assert set(headers) == set(fields) # Order may change

                assert len(body) == len(variables)

                for row, variable in zip(body, variables):
                    for element, field in zip(row, headers):
                        # NOTE: The elements are *NOT* JSON serialized
                        if field == "messages":
                            # Here, element is of the form '[{a: b}]',
                            # So although we haven't serialized it
                            # to JSON, we can still deserialize this particular object
                            element = json.loads(element)
                            assert isinstance(element, list) and element == []
                        elif field == "bot_is_active":
                            # Here, field == 'False', which is not 'false'
                            assert element in ('True', 'False')
                        elif field == "num_msgs":
                            # Here, again we can use the hacky method and
                            # deserialize it using json.loads('0')
                            element = json.loads(element)
                            assert isinstance(element, int) and element >= 0
                        else:
                            if field in variable_fields:
                                # The variable values must match
                                assert element == variable[field]
                            else:
                                # Fuck the other objects. I don't give a shit
                                assert isinstance(element, str)
                
                # Now override using frontend POST
                mapping = {'bot_id': 'Bot ID', 'room_name': 'Room Name', None: None, '@name': 'Name', '@email': 'Email'}
                rev_mapping = {mapping[key]: key for key in mapping if key is not None}

                headers = list({key: mapping[key]} if key is not None else None for key in mapping) # type: ignore

                header_data = {
                    'headers': headers
                }
                response = client.post(f"/api/chatdata/headers/{bot_hash}", data=header_data, format="json")
                assert response.status_code == 200

                # Export the data now
                response = client.get(f"/api/chatdata/export/bot/{bot_hash}/csv")
                assert response.status_code == 200

                # Deal with the exported csv data
                content = response.content.decode('utf-8')
                csv_reader = csv.reader(io.StringIO(content))

                # Segregate the body and the headers
                body = list(csv_reader)
                headers = body.pop(0)

                reqd_fields = ["Bot ID", "Room Name"] # These now become the column names
                variable_fields = ["Name", "Email"] # Now become the column names

                fields = reqd_fields + variable_fields

                assert set(headers) == set(fields) # Order may change

                assert len(body) == len(variables)

                for row, variable in zip(body, variables):
                    for element, field in zip(row, headers):
                        # NOTE: The elements are *NOT* JSON serialized
                        if field in variable_fields:
                            # The variable values must match
                            assert element == variable[rev_mapping[field]]
                        else:
                            # Fuck the other objects. I don't give a shit
                            assert isinstance(element, str)
                
                # Delete the frontend override from the session
                session = client.session
                assert f'chatdata_fields_{bot_hash}' in session and f'chatdata_column_names_{bot_hash}' in session
                del session[f'chatdata_fields_{bot_hash}']
                del session[f'chatdata_column_names_{bot_hash}']
                session.save()
                
                # Test export of xlsx
                response = client.get(f"/api/chatdata/export/bot/{bot_hash}/xlsx")
                assert response.status_code == 200

                content = io.BytesIO(response.content)
                
                workbook = xlrd.open_workbook(file_contents=content.getvalue()) 
                sheet = workbook.sheet_by_index(0)

                num_rows = sheet.nrows
                headers = sheet.row_values(0)

                reqd_fields = ["room_id", "created_on", "room_name", "messages", "bot_id", "chatbot_type", "bot_is_active", "is_lead", "status"]
                variable_fields = list(variables[0].keys())

                fields = reqd_fields + variable_fields

                assert set(headers) == set(fields) # Order may change

                assert num_rows == len(variables) + 1 # Excluding headers

                for row_idx, variable in zip(range(1, num_rows), variables):
                    row = sheet.row_values(row_idx)
                    assert len(row) == len(fields)
                    for element, field in zip(row, headers):
                        # Here, the elements are JSON serialized for xlsx
                        if field == "messages":
                            element = json.loads(element)
                            assert isinstance(element, list) and element == []
                        elif field == "bot_is_active":
                            assert element in ('true', 'false')
                        elif field == "num_msgs":
                            # Here, again we can use the hacky method and
                            # deserialize it using json.loads('0')
                            element = json.loads(element)
                            assert isinstance(element, int) and element >= 0
                        else:
                            if field in variable_fields:
                                # The variable values must match
                                assert element == variable[field]
                            else:
                                # Fuck the other objects. I don't give a shit
                                assert isinstance(element, str)

        client.logout()

    
    @pytest.mark.django_db
    def test_send_email(self, client: APIClient, setup_chatdata: pytest.fixture) -> None:
        user, bots, variables, _ = setup_chatdata
        
        # Login first
        client.login(username=user, password='test')

        for bot_map in bots:
            bot_hash, bot_name = list(bot_map.items())[0]
            if bot_name == "Test Bot":
                response = client.get(f"/api/chatdata/bot/{bot_hash}")
                assert response.status_code == 200
                
                data = json.loads(response.content)
                assert len(data) == 10 # 10 Chats

                # Send the Email
                response = client.post(f"/api/chatdata/email/bot/{bot_hash}", data={}, format="json")
                assert response.status_code == 200

                assert len(mail.outbox) == 1

                msg = mail.outbox[-1]
                
                assert msg.to == [user.email]
                assert msg.subject == 'Your Autovista Chatbot History'

                assert len(msg.attachments) == 1

                attachment = msg.attachments[0]
                name, content = attachment[0], attachment[1]
                assert name == f"{bot_name}.csv"

                # Deal with the exported csv data
                csv_reader = csv.reader(io.StringIO(content))

                # Segregate the body and the headers
                body = list(csv_reader)
                headers = body.pop(0)

                reqd_fields = ["room_id", "created_on", "room_name", "messages", "bot_id", "chatbot_type", "bot_is_active", "is_lead", "status"]
                variable_fields = list(variables[0].keys())

                fields = reqd_fields + variable_fields

                assert set(headers) == set(fields) # Order may change

                assert len(body) == len(variables)

                for row, variable in zip(body, variables):
                    for element, field in zip(row, headers):
                        # NOTE: The elements are *NOT* JSON serialized
                        if field == "messages":
                            # Here, element is of the form '[{a: b}]',
                            # So although we haven't serialized it
                            # to JSON, we can still deserialize this particular object
                            element = json.loads(element)
                            assert isinstance(element, list) and element == []
                        elif field == "bot_is_active":
                            # Here, field == 'False', which is not 'false'
                            assert element in ('True', 'False')
                        elif field == "num_msgs":
                            # Here, again we can use the hacky method and
                            # deserialize it using json.loads('0')
                            element = json.loads(element)
                            assert isinstance(element, int) and element >= 0
                        else:
                            if field in variable_fields:
                                # The variable values must match
                                assert element == variable[field]
                            else:
                                # Fuck the other objects. I don't give a shit
                                assert isinstance(element, str)
                
                # Now override using frontend POST
                mapping = {'bot_id': 'Bot ID', 'room_name': 'Room Name', None: None, '@name': 'Name', '@email': 'Email'}
                rev_mapping = {mapping[key]: key for key in mapping if key is not None}

                headers = list({key: mapping[key]} if key is not None else None for key in mapping) # type: ignore

                header_data = {
                    'headers': headers
                }
                response = client.post(f"/api/chatdata/headers/{bot_hash}", data=header_data, format="json")
                assert response.status_code == 200

                # Send the Email
                response = client.post(f"/api/chatdata/email/bot/{bot_hash}", data={}, format="json")
                assert response.status_code == 200

                assert len(mail.outbox) == 2 # Second Mail

                msg = mail.outbox[-1]
                
                assert msg.to == [user.email]
                assert msg.subject == 'Your Autovista Chatbot History'

                assert len(msg.attachments) == 1

                attachment = msg.attachments[0]
                name, content = attachment[0], attachment[1]
                assert name == f"{bot_name}.csv"

                # Deal with the exported csv data
                csv_reader = csv.reader(io.StringIO(content))

                # Segregate the body and the headers
                body = list(csv_reader)
                headers = body.pop(0)

                reqd_fields = ["Bot ID", "Room Name"] # These now become the column names
                variable_fields = ["Name", "Email"] # Now become the column names

                fields = reqd_fields + variable_fields

                assert set(headers) == set(fields) # Order may change

                assert len(body) == len(variables)

                for row, variable in zip(body, variables):
                    for element, field in zip(row, headers):
                        # NOTE: The elements are *NOT* JSON serialized
                        if field in variable_fields:
                            # The variable values must match
                            assert element == variable[rev_mapping[field]]
                        else:
                            # Fuck the other objects. I don't give a shit
                            assert isinstance(element, str)
                
                # Delete the frontend override from the session
                session = client.session
                assert f'chatdata_fields_{bot_hash}' in session and f'chatdata_column_names_{bot_hash}' in session
                del session[f'chatdata_fields_{bot_hash}']
                del session[f'chatdata_column_names_{bot_hash}']
                session.save()
                
                # Send the Email
                response = client.post(f"/api/chatdata/email/bot/{bot_hash}/xlsx", data={}, format="json")
                assert response.status_code == 200

                assert len(mail.outbox) == 3 # Third Mail

                msg = mail.outbox[-1]
                
                assert msg.to == [user.email]
                assert msg.subject == 'Your Autovista Chatbot History'

                assert len(msg.attachments) == 1

                attachment = msg.attachments[0]
                name, content = attachment[0], attachment[1]
                assert name == f"{bot_name}.xlsx"

                content = io.BytesIO(content)
                
                workbook = xlrd.open_workbook(file_contents=content.getvalue()) 
                sheet = workbook.sheet_by_index(0)

                num_rows = sheet.nrows
                headers = sheet.row_values(0)

                reqd_fields = ["room_id", "created_on", "room_name", "messages", "bot_id", "chatbot_type", "bot_is_active", "is_lead", "status"]
                variable_fields = list(variables[0].keys())

                fields = reqd_fields + variable_fields

                assert set(headers) == set(fields) # Order may change

                assert num_rows == len(variables) + 1 # Excluding headers

                for row_idx, variable in zip(range(1, num_rows), variables):
                    row = sheet.row_values(row_idx)
                    assert len(row) == len(fields)
                    for element, field in zip(row, headers):
                        # Here, the elements are JSON serialized for xlsx
                        if field == "messages":
                            element = json.loads(element)
                            assert isinstance(element, list) and element == []
                        elif field == "bot_is_active":
                            assert element in ('true', 'false')
                        elif field == "num_msgs":
                            # Here, again we can use the hacky method and
                            # deserialize it using json.loads('0')
                            element = json.loads(element)
                            assert isinstance(element, int) and element >= 0
                        else:
                            if field in variable_fields:
                                # The variable values must match
                                assert element == variable[field]
                            else:
                                # Fuck the other objects. I don't give a shit
                                assert isinstance(element, str)

        client.logout()
