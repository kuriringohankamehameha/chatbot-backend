import asyncio
import glob
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
from asgiref.sync import sync_to_async
from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.sessions import SessionMiddlewareStack
from channels.testing import WebsocketCommunicator
from django.apps import apps
from django.conf import settings
from django.contrib import auth
from django.contrib.auth.models import AnonymousUser
from django.core import management
from django.urls import re_path, reverse
from mixer.backend.django import mixer
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.clientwidget.consumers import TemplateChatConsumer
from apps.clientwidget.models import ChatRoom

# Session settings
SessionStore = import_module(settings.SESSION_ENGINE).SessionStore # type: ignore

# Use an in-memory channel layer for testing
TEST_CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels.layers.InMemoryChannelLayer',
    },
}


@mixer.middleware(User)
def encrypt_password(user: 'User') -> 'User':
    user.set_password('test')
    return user


@pytest.fixture
def client() -> APIClient:
    return APIClient()


@pytest.fixture
def populate_db(request) -> Iterator[Tuple[List[User], List[str], List[dict]]]:
    """Sets up the Database with example data for the template Chatbot flow.

    Yields:
        Iterator[Tuple[List[User], List[str], List[dict]]]: An iterator of (`User`s, `bot_id`s, `variable`s)
    """
    print('Setup')
    # Create Users
    NUM_USERS = request.param['num_users']
    users = mixer.cycle(NUM_USERS).blend(User, is_superuser=True)
    bots = [] # Assume one bot per user
    variables = [] # Variables per bot

    client = APIClient()

    # File information
    curr_file = str(os.getenv('PYTEST_CURRENT_TEST'))
    curr_file = curr_file.split('::')[0]
    curr_dir = '/'.join(curr_file.split('/')[:-1])

    bot_dir = os.path.join(curr_dir, 'bots')
    bot_files = sorted(glob.glob(os.path.join(bot_dir, 'test_*.json')))
    variable_files = sorted(glob.glob(os.path.join(bot_dir, 'variables_*.json')))

    for user, bot_file, variable_file in zip(users, itertools.cycle(bot_files), itertools.cycle(variable_files)):
        # Login first
        client.login(username=user, password='test')
        user = auth.get_user(client) # type: ignore
        assert user.is_authenticated

        # Now make a new bot for the user
        with open(bot_file) as json_file:
            bot_json = json.load(json_file)
        
        response = client.post('/api/chatbox', data=bot_json, format="json")
        assert response.status_code == 200 or response.status_code == 201

        data = json.loads(response.content)
        bot_hash = data['bot_hash']
        assert bot_hash is not None

        # Add to the list of bots
        bots.append(bot_hash)

        # Now place the bot_full_json
        response = client.put(f'/api/chatbox/{bot_hash}', data=bot_json, format="json")
        assert response.status_code == 200 or response.status_code == 201

        # Check the json
        data = json.loads(response.content)
        assert 'bot_data_json' in data and 'bot_variable_json' in data
        bot_data_json, bot_variable_json = data['bot_data_json'], data['bot_variable_json']
        assert bot_data_json is not None and bot_variable_json is not None

        # Verify that variables match
        with open(variable_file) as json_file:
            variable_json = json.load(json_file)
        assert 'bot_variable_json' in variable_json and bot_variable_json == variable_json['bot_variable_json']

        variables.append(bot_variable_json)

        response = client.get('/api/chatbox')
        assert response.status_code == 200

        data = json.loads(response.content)
        assert len(data) == 1
        
        # Logout
        response = client.get('/api/auth/logout')
        assert response.status_code == 200 or response.status_code == 201
        client.logout()
    
    assert len(users) == len(bots)

    yield (users, bots, variables)
    
    print("Teardown")
    
    # Clear all sessions
    management.call_command('clear_sessions')


@pytest.fixture
def populate_lead_db(request) -> Iterator[Tuple[List[User], List[str], List[dict]]]:
    """Sets up the Database with example data for the LEAD template Chatbot flow.

    Yields:
        Iterator[Tuple[List[User], List[str], List[dict]]]: An iterator of (`User`s, `bot_id`s, `variable`s)
    """
    print('Setup')
    # Create Users
    NUM_USERS = request.param['num_users']
    users = mixer.cycle(NUM_USERS).blend(User, is_superuser=True)
    bots = [] # Assume one bot per user
    variables = [] # Variables per bot

    client = APIClient()

    # File information
    curr_file = str(os.getenv('PYTEST_CURRENT_TEST'))
    curr_file = curr_file.split('::')[0]
    curr_dir = '/'.join(curr_file.split('/')[:-1])

    bot_dir = os.path.join(curr_dir, 'bots')
    bot_files = sorted(glob.glob(os.path.join(bot_dir, 'test_lead*.json')))
    variable_files = sorted(glob.glob(os.path.join(bot_dir, 'variables_lead*.json')))

    for user, bot_file, variable_file in zip(users, itertools.cycle(bot_files), itertools.cycle(variable_files)):
        # Login first
        client.login(username=user, password='test')
        user = auth.get_user(client) # type: ignore
        assert user.is_authenticated

        # Now make a new bot for the user
        with open(bot_file) as json_file:
            bot_json = json.load(json_file)
        
        response = client.post('/api/chatbox', data=bot_json, format="json")
        assert response.status_code == 200 or response.status_code == 201

        data = json.loads(response.content)
        bot_hash = data['bot_hash']
        assert bot_hash is not None

        # Add to the list of bots
        bots.append(bot_hash)

        # Now place the bot_full_json
        response = client.put(f'/api/chatbox/{bot_hash}', data=bot_json, format="json")
        assert response.status_code == 200 or response.status_code == 201

        # Check the json
        data = json.loads(response.content)
        assert 'bot_data_json' in data and 'bot_variable_json' in data and 'bot_lead_json' in data and 'variable_columns' in data
        bot_data_json, bot_variable_json = data['bot_data_json'], data['bot_variable_json']
        assert bot_data_json is not None and bot_variable_json is not None

        # bot_lead_json must NOT be empty
        assert data['bot_lead_json'] not in (None, {})

        # Only @name and @email are lead fields for this bot
        assert data['bot_lead_json'] == {'@name': '', '@email': ''}

        # variable_columns must be the same as bot_variable_json
        assert set(data['variable_columns']) == set(data['bot_variable_json'].keys())

        # Verify that variables match
        with open(variable_file) as json_file:
            variable_json = json.load(json_file)
        assert 'bot_variable_json' in variable_json and bot_variable_json == variable_json['bot_variable_json']

        variables.append(bot_variable_json)

        response = client.get('/api/chatbox')
        assert response.status_code == 200

        data = json.loads(response.content)
        assert len(data) == 1
        
        # Logout
        response = client.get('/api/auth/logout')
        assert response.status_code == 200 or response.status_code == 201
        client.logout()
    
    assert len(users) == len(bots)

    yield (users, bots, variables)
    
    print("Teardown")
    
    # Clear all sessions
    management.call_command('clear_sessions')


@pytest.mark.django_db(transaction=True)
class TestWebSocket:

    num_users = 1


    @pytest.mark.asyncio
    async def test_websocket_consumer(self, settings) -> None:
        settings.CHANNEL_LAYERS = TEST_CHANNEL_LAYERS
        application = ProtocolTypeRouter({
            'websocket': AuthMiddlewareStack(
                SessionMiddlewareStack(
                    URLRouter([
                        re_path(r'ws/chat/(?P<room_name>\w+)/$', TemplateChatConsumer)
                    ])
                )
            )
        })

        # Create the test room in ChatRoom
        room_instance, _ = ChatRoom.objects.get_or_create(room_name='test', bot_id=uuid.uuid4())
        
        assert room_instance.room_name == 'test'
        
        communicator = WebsocketCommunicator(application, "/ws/chat/test/")
        connected, _ = await communicator.connect()
        
        assert connected == True
        
        # Send a sample message from end_user
        await communicator.send_json_to({"user": "end_user", "message": {"userInputVal": "User Message!"}})
        # response contains other fields too! So check only the necessary ones
        response = await communicator.receive_json_from(timeout=3)
        
        assert response["user"] == "end_user" and response["message"]["userInputVal"] == "User Message!"
        
        # And from admin
        await communicator.send_json_to({"user": "admin", "message": "Admin Message!"})
        # response contains other fields too! So check only the necessary ones
        response = await communicator.receive_json_from()
        
        assert response["user"] == "admin" and response["message"] == "Admin Message!"
        
        # Close
        await communicator.disconnect()

    
    @pytest.mark.parametrize('populate_db', [{'num_users': num_users}], indirect=True)
    @pytest.mark.asyncio
    async def test_template_flow(self, settings, client: APIClient, populate_db: pytest.fixture) -> None:
        settings.CHANNEL_LAYERS = TEST_CHANNEL_LAYERS
        application = ProtocolTypeRouter({
            'websocket': AuthMiddlewareStack(
                SessionMiddlewareStack(
                    URLRouter([
                        re_path(r'ws/chat/(?P<room_name>\w+)/$', TemplateChatConsumer)
                    ])
                )
            )
        })

        _, bots, variables = populate_db
        for (bot_id, variable) in zip(bots, variables):
            # Start a new session for the template chat
            response = client.get(f'/api/clientwidget/session/{bot_id}')
            assert response.status_code == 200

            response_data = json.loads(response.content)
            assert response_data["nodeType"] == "INIT" and response_data["room_name"] is not None and response_data["variables"] == variable
            
            room_name = response_data["room_name"]

            # Create the test room in ChatRoom
            room_instance, _ = ChatRoom.objects.get_or_create(room_name=room_name, bot_id=bot_id)
            
            assert room_instance.room_name == room_name
            
            communicator = WebsocketCommunicator(application, f"/ws/chat/{room_name}/")
            connected, _ = await communicator.connect()
            
            assert connected == True

            user_inputs = [] # List of variable inputs per bot session
            variable_dict = dict() # And the corresponding dictionary

            while not ("nodeType" in response_data and response_data["nodeType"] == "END"):              
                # Wait for 2 seconds
                time.sleep(2)
                # The message to be sent
                message = dict()
                payload = dict()
                # Set some flags
                yes_no, multi_choice = False, False
                if "nodeType" in response_data and response_data["nodeType"] == "YES_NO":
                    # If YES / NO button
                    yes_no = True
                    choice = random.choice(["Yes", "No"])
                    for node in response_data["buttons"]:
                        if node["text"] == choice:
                            payload['target_id'] = node['targetId']
                            payload['post_data'] = choice
                elif "nodeType" in response_data and response_data["nodeType"] == "MULTI_CHOICE":
                    # If Multi choice button
                    multi_choice = True
                    choices = set()
                    for node in response_data["buttons"]:
                        choices.add(node["text"])
                    payload['target_id'] = node['targetId']
                    payload['post_data'] = random.choice(tuple(choices))
                elif "nodeType" in response_data and response_data["nodeType"] == "INIT":
                    # Try to go to the next target_id node
                    payload['target_id'] = response_data["targetId"]
                else:
                    # Try to go to the next target_id node
                    payload['target_id'] = response_data["targetId"]

                if "variable" in response_data:
                    payload["variable"] = response_data["variable"]
                    if multi_choice:
                        # Multi choice variable already set
                        user_inputs.append(payload["post_data"])
                        variable_dict[response_data['variable']] = payload["post_data"]
                    elif yes_no:
                        # Yes / No variable already set
                        user_inputs.append(payload["post_data"])
                        variable_dict[response_data['variable']] = payload["post_data"]
                    else:
                        # Give a random input
                        length = 10
                        payload["post_data"] = ''.join(random.choice(string.ascii_letters) for i in range(length))
                        user_inputs.append(payload["post_data"])
                        variable_dict[response_data['variable']] = payload["post_data"]
                
                # Set the bot parameters
                message["user"] = "bot"
                message["bot_id"] = str(bot_id)
                message["data"] = payload # type: ignore

                await communicator.send_json_to(message)
                response_data = await communicator.receive_json_from(timeout=3)
                                
                # If the bot is still active                
                if response_data["user"] == "bot":
                    if 'data' in response_data:
                        response_data = response_data['data']
                    else:
                        break
                else:
                    break
            
            # Disconnect
            await communicator.disconnect()


    @pytest.mark.parametrize('populate_db', [{'num_users': num_users}], indirect=True)
    @pytest.mark.asyncio
    async def test_livechat_flow(self, settings, client: APIClient, populate_db: pytest.fixture) -> None:
        # settings.CHANNEL_LAYERS = TEST_CHANNEL_LAYERS
        application = ProtocolTypeRouter({
            'websocket': AuthMiddlewareStack(
                SessionMiddlewareStack(
                    URLRouter([
                        re_path(r'ws/chat/(?P<room_name>\w+)/$', TemplateChatConsumer)
                    ])
                )
            )
        })

        # Create a dummy admin user
        admin_user = mixer.blend(User, role='AO')

        # Login as admin operator
        admin = APIClient()
        admin.login(username=admin_user, password='test')
        user = auth.get_user(admin) # type: ignore
        assert user.is_authenticated

        _, bots, variables = populate_db
        for (bot_id, variable) in zip(bots, variables):
            # Start a new session for the template chat
            response = client.get(f'/api/clientwidget/session/{bot_id}')
            assert response.status_code == 200

            response_data = json.loads(response.content)
            assert response_data["nodeType"] == "INIT" and response_data["room_name"] is not None and response_data["variables"] == variable
            
            room_name = response_data["room_name"]

            # Create the test room in ChatRoom
            room_instance, _ = ChatRoom.objects.get_or_create(room_name=room_name, bot_id=bot_id)
            
            assert room_instance.room_name == room_name
            
            # Create 2 communicators - One for the client and one for the admin
            client_socket = WebsocketCommunicator(application, f"/ws/chat/{room_name}/")
            admin_socket = WebsocketCommunicator(application, f"/ws/chat/{room_name}/")

            admin_socket.scope["user"] = admin_user

            client_connected, _ = await client_socket.connect()
            
            assert client_connected == True

            admin_connected = None

            user_inputs = [] # List of variable inputs per bot session
            variable_dict = room_instance.variables # And the corresponding dictionary from the room instance

            is_livechat = False

            while not ("nodeType" in response_data and response_data["nodeType"] == "END"):              
                # Wait for 2 seconds
                time.sleep(2)
                
                if admin_connected == True:
                    # Switch to Livechat
                    is_livechat = True
                    break

                # The message to be sent
                message = dict()
                payload = dict()
                # Set some flags
                yes_no, multi_choice = False, False
                if "nodeType" in response_data and response_data["nodeType"] == "YES_NO":
                    # If YES / NO button
                    yes_no = True
                    choice = random.choice(["Yes", "No"])
                    for node in response_data["buttons"]:
                        if node["text"] == choice:
                            payload['target_id'] = node['targetId']
                            payload['post_data'] = choice
                elif "nodeType" in response_data and response_data["nodeType"] == "MULTI_CHOICE":
                    # If Multi choice button
                    multi_choice = True
                    choices = set()
                    for node in response_data["buttons"]:
                        choices.add(node["text"])
                    payload['target_id'] = node['targetId']
                    payload['post_data'] = random.choice(tuple(choices))
                elif "nodeType" in response_data and response_data["nodeType"] == "INIT":
                    # Try to go to the next target_id node
                    payload['target_id'] = response_data["targetId"]
                else:
                    # Try to go to the next target_id node
                    payload['target_id'] = response_data["targetId"]

                if "variable" in response_data:
                    payload["variable"] = response_data["variable"]
                    if multi_choice:
                        # Multi choice variable already set
                        user_inputs.append(payload["post_data"])
                        variable_dict[response_data['variable']] = payload["post_data"]
                    elif yes_no:
                        # Yes / No variable already set
                        user_inputs.append(payload["post_data"])
                        variable_dict[response_data['variable']] = payload["post_data"]
                    else:
                        # Give a random input
                        length = 10
                        payload["post_data"] = ''.join(random.choice(string.ascii_letters) for i in range(length))
                        user_inputs.append(payload["post_data"])
                        variable_dict[response_data['variable']] = payload["post_data"]
                
                # Set the bot parameters
                message["user"] = "bot"
                message["bot_id"] = str(bot_id)
                message["data"] = payload # type: ignore

                await client_socket.send_json_to(message)
                response_data = await client_socket.receive_json_from(timeout=3)
                                
                # If the bot is still active                
                if response_data["user"] == "bot":
                    if 'data' in response_data:
                        response_data = response_data['data']
                    else:
                        break
                else:
                    break

                if (yes_no == True or multi_choice == True) and admin_connected is None:
                    # Make the admin enter at this point
                    admin_connected, _ = await admin_socket.connect()
                    assert admin_connected == True


            while is_livechat == True:
                # Send from admin communicator
                await admin_socket.send_json_to({"user": "admin", "message": "Hello from admin"})
                
                futures = await asyncio.gather(
                    client_socket.receive_json_from(),
                    admin_socket.receive_json_from(),
                )
                response_data_client, response_data_admin = futures

                assert response_data_client == response_data_admin
                assert response_data_admin["user"] == "admin" and response_data_admin["message"] == "Hello from admin" # type: ignore
                
                # Now send from client communicator
                await client_socket.send_json_to({"user": "end_user", "message": {"userInputVal": "Hello from client"}})

                futures = await asyncio.gather(
                    client_socket.receive_json_from(),
                    admin_socket.receive_json_from(),
                )
                response_data_client, response_data_admin = futures

                assert response_data_client == response_data_admin
                assert response_data_client["user"] == "end_user" and response_data_client["message"]["userInputVal"] == "Hello from client" # type: ignore
                
                # Now exit
                break

            # Verify session variables
            response = admin.get(f"/api/clientwidget/{room_name}/sessionvariables")
            assert response.status_code == 200
            session_variables = json.loads(response.content)
            assert session_variables == variable_dict

            # Variables in DB must be empty
            response = admin.get(f"/api/clientwidget/{room_name}/variables")
            assert response.status_code == 200
            variables = json.loads(response.content)
            assert variables == {key: "" for key in variable_dict}

            # Now verify the chat session history
            response = admin.get(f"/api/clientwidget/{room_name}/sessionhistory")
            assert response.status_code == 200

            session_history = json.loads(response.content)
            assert len(session_history) == 2
            assert session_history == [{"user": "admin", "message": "Hello from admin"}, {"user": "end_user", "message": {"userInputVal": "Hello from client"}}]

            # DB History must be empty
            response = admin.get(f"/api/clientwidget/{room_name}/history")
            assert response.status_code == 400 or response.status_code == 200
            if response.status_code == 200:
                # List must be empty
                history = json.loads(response.content)
                assert len(history) == 0
            
            # Disconnect
            await client_socket.disconnect()
            await admin_socket.disconnect()

            # Now session history must be empty
            response = admin.get(f"/api/clientwidget/{room_name}/sessionhistory")
            assert response.status_code == 400 or response.status_code == 200
            if response.status_code == 200:
                # List must be empty   
                flushed_history = json.loads(response.content)
                assert len(flushed_history) == 0

            # While DB history is not
            response = admin.get(f"/api/clientwidget/{room_name}/history")
            assert response.status_code == 200

            history = json.loads(response.content)
            assert history == session_history

            # Variables in session must be empty
            response = admin.get(f"/api/clientwidget/{room_name}/sessionvariables")
            assert response.status_code == 404

            # While it must be updated in DB
            response = admin.get(f"/api/clientwidget/{room_name}/variables")
            assert response.status_code == 200
            variables = json.loads(response.content)
            assert variables == session_variables

    
    @pytest.mark.parametrize('populate_db', [{'num_users': 1}], indirect=True)
    @pytest.mark.asyncio
    async def test_emit_to_socket(self, settings, client: APIClient, populate_db: pytest.fixture) -> None:
        # settings.CHANNEL_LAYERS = TEST_CHANNEL_LAYERS
        application = ProtocolTypeRouter({
            'websocket': AuthMiddlewareStack(
                SessionMiddlewareStack(
                    URLRouter([
                        re_path(r'ws/chat/(?P<room_name>\w+)/$', TemplateChatConsumer)
                    ])
                )
            )
        })

        # Create a dummy admin user
        admin_user = mixer.blend(User, role='AO')

        # Login as admin operator
        admin = APIClient()
        admin.login(username=admin_user, password='test')
        user = auth.get_user(admin) # type: ignore
        assert user.is_authenticated

        _, bots, variables = populate_db
        for (bot_id, variable) in zip(bots, variables):
            # Start a new session for the template chat
            response = client.get(f'/api/clientwidget/session/{bot_id}')
            assert response.status_code == 200

            response_data = json.loads(response.content)
            assert response_data["nodeType"] == "INIT" and response_data["room_name"] is not None and response_data["variables"] == variable
            
            room_name = response_data["room_name"]

            # Create the test room in ChatRoom
            room_instance, _ = ChatRoom.objects.get_or_create(room_name=room_name, bot_id=bot_id)
            
            assert room_instance.room_name == room_name
            
            client_socket = WebsocketCommunicator(application, f"/ws/chat/{room_name}/")

            # Before connecting, test an emit API message. It should be stored to session
            response = client.post(
                reverse('client widget send to websocket', kwargs={'room_id': room_instance.room_id}),
                data={
                    'user': 'bot_parsed',
                    'message': [{'user': 'end_user', 'message': {'userInputVal': 'Message1'}}],
                }, format="json"
            )
            assert response.status_code == 200

            # Now look at the session
            response = admin.get(f"/api/clientwidget/{room_name}/sessionhistory")
            assert response.status_code == 200

            session_data = json.loads(response.content)
            assert len(session_data) == 1 and session_data == [{'user': 'end_user', 'message': {'userInputVal': 'Message1'}}]

            # Now connect to the websocket
            client_connected, _ = await client_socket.connect()
            
            assert client_connected == True

            # Send a sample message from end_user
            await client_socket.send_json_to({"user": "admin", "message": "Admin Message!"})
            # response contains other fields too! So check only the necessary ones
            response = await client_socket.receive_json_from(timeout=2)
            
            assert response["user"] == "admin" and response["message"] == "Admin Message!"

            response = await sync_to_async(client.post)(
                reverse('client widget send to websocket', kwargs={'room_id': room_instance.room_id}),
                data={
                    'user': 'bot_parsed',
                    'message': [{'user': 'end_user', 'message': {'userInputVal': 'Message2'}}],
                }, format="json"
            )
            assert response.status_code == 200
            response = await client_socket.receive_json_from(timeout=3)
            assert response["user"] == "bot_parsed" and response["message"] == [{'user': 'end_user', 'message': {'userInputVal': 'Message2'}}]

            response = admin.get(f"/api/clientwidget/{room_name}/sessionhistory")
            assert response.status_code == 200

            session_data = json.loads(response.content)
            assert len(session_data) == 3
            assert session_data[0]['user'] == 'end_user' and session_data[0]['message']['userInputVal'] == 'Message1'
            assert session_data[1]['user'] == 'admin' and session_data[1]['message'] == 'Admin Message!'
            assert session_data[2]['user'] == 'end_user' and session_data[2]['message']['userInputVal'] == 'Message2'
            
            # Close
            await client_socket.disconnect()


    @pytest.mark.parametrize('populate_lead_db', [{'num_users': num_users}], indirect=True)
    @pytest.mark.asyncio
    async def test_lead_flow(self, settings, client: APIClient, populate_lead_db: pytest.fixture) -> None:
        # settings.CHANNEL_LAYERS = TEST_CHANNEL_LAYERS
        application = ProtocolTypeRouter({
            'websocket': AuthMiddlewareStack(
                SessionMiddlewareStack(
                    URLRouter([
                        re_path(r'ws/chat/(?P<room_name>\w+)/$', TemplateChatConsumer)
                    ])
                )
            )
        })

        # We'll have two clients chat with the bot
        # One will be a lead and one won't
        clients = [client, APIClient()]

        room_names = []

        users, bots, variables = populate_lead_db
        for (user, bot_id, variable) in zip(users, bots, variables):
            for idx, client in enumerate(clients): 
                # Start a new session for the template chat
                response = client.get(f'/api/clientwidget/session/{bot_id}')
                assert response.status_code == 200

                response_data = json.loads(response.content)
                assert response_data["nodeType"] == "INIT" and response_data["room_name"] is not None and response_data["variables"] == variable
                
                room_name = response_data["room_name"]

                # Create the test room in ChatRoom
                room_instance, _ = ChatRoom.objects.get_or_create(room_name=room_name, bot_id=bot_id)
                
                assert room_instance.room_name == room_name

                room_names.append(room_name)
                
                communicator = WebsocketCommunicator(application, f"/ws/chat/{room_name}/")
                connected, _ = await communicator.connect()
                
                assert connected == True

                user_inputs = [] # List of variable inputs per bot session
                variable_dict = dict() # And the corresponding dictionary

                while not ("nodeType" in response_data and response_data["nodeType"] == "END"):              
                    # Wait for 2 seconds
                    time.sleep(2)
                    # The message to be sent
                    message = dict()
                    payload = dict()
                    # Set some flags
                    yes_no, multi_choice = False, False
                    if "nodeType" in response_data and response_data["nodeType"] == "YES_NO":
                        # If YES / NO button
                        yes_no = True
                        choice = random.choice(["Yes", "No"])
                        
                        for node in response_data["buttons"]:
                            if node["text"] == choice:
                                payload['target_id'] = node['targetId']
                                payload['post_data'] = choice
                    elif "nodeType" in response_data and response_data["nodeType"] == "MULTI_CHOICE":
                        # If Multi choice button
                        multi_choice = True
                        choices = set()
                        for node in response_data["buttons"]:
                            choices.add(node["text"])
                        payload['target_id'] = node['targetId']
                        payload['post_data'] = random.choice(tuple(choices))
                    elif "nodeType" in response_data and response_data["nodeType"] == "INIT":
                        # Try to go to the next target_id node
                        payload['target_id'] = response_data["targetId"]
                    else:
                        # Try to go to the next target_id node
                        payload['target_id'] = response_data["targetId"]

                    if "variable" in response_data:
                        payload["variable"] = response_data["variable"]
                        if multi_choice:
                            # Multi choice variable already set
                            user_inputs.append(payload["post_data"])
                            variable_dict[response_data['variable']] = payload["post_data"]
                        elif yes_no:
                            # Yes / No variable already set
                            user_inputs.append(payload["post_data"])
                            variable_dict[response_data['variable']] = payload["post_data"]
                        else:
                            # Give a random input
                            length = 10
                            payload["post_data"] = ''.join(random.choice(string.ascii_letters) for i in range(length))
                            user_inputs.append(payload["post_data"])
                            variable_dict[response_data['variable']] = payload["post_data"]
                    
                    # Set the bot parameters
                    message["user"] = "bot"
                    message["bot_id"] = str(bot_id)
                    message["data"] = payload # type: ignore

                    if idx == 0 and 'variable' in payload and payload['variable'] == '@email':
                        # Disconnect here for non lead client
                        # He won't be a lead
                        break

                    await communicator.send_json_to(message)
                    response_data = await communicator.receive_json_from(timeout=3)
                                    
                    # If the bot is still active                
                    if response_data["user"] == "bot":
                        if 'data' in response_data:
                            response_data = response_data['data']
                        else:
                            break
                    else:
                        break
                
                # Disconnect
                await communicator.disconnect()

            # Now let's look at chatdata
            client.login(username=user, password='test')
            user = auth.get_user(client) # type: ignore
            assert user.is_authenticated

            response = client.get(f"/api/chatdata/bot/{bot_id}")
            assert response.status_code == 200

            chatdata = json.loads(response.content)
            assert len(chatdata) == 2 and len(chatdata) == len(room_names) # 2 Chats

            response = client.get(f"/api/chatbox/{bot_id}")
            assert response.status_code == 200

            data = json.loads(response.content)
            lead_fields = list(data['bot_lead_json'].keys())

            for chat_data in chatdata:
                assert chat_data['room_name'] in room_names
                if chat_data['room_name'] == room_names[0]:
                    # Non Lead Chat
                    assert chat_data['is_lead'] == False
                    # Atleast one of the lead fields must be empty
                    empty_fields = list(filter(lambda field: chat_data['variables'][field] == '', lead_fields))
                    assert empty_fields not in (None, []) and '@email' in empty_fields
                elif chat_data['room_name'] == room_names[1]:
                    # Lead Chat
                    assert chat_data['is_lead'] == True
                    # None of the lead fields must be empty
                    empty_fields = list(filter(lambda field: chat_data['variables'][field] == '', lead_fields))
                    assert empty_fields in (None, [])
