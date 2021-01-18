import glob
import itertools
import json
import os
import random
import string
import time
from typing import Callable, Iterator, List, Tuple

import pytest
from django.apps import apps
from django.contrib import auth
from django.contrib.auth.models import AnonymousUser
from django.core import management
from django.urls import reverse
from mixer.backend.django import mixer
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.chatbox.models import Chatbox
from apps.clientwidget.models import ChatRoom, ChatAssign


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
        assert 'bot_data_json' in data and 'bot_variable_json' in data and 'bot_lead_json' in data and 'variable_columns' in data
        bot_data_json, bot_variable_json = data['bot_data_json'], data['bot_variable_json']
        assert bot_data_json is not None and bot_variable_json is not None

        # bot_lead_json must be empty
        # assert data['bot_lead_json'] in (None, {})
        # Fallback Option
        assert data['bot_lead_json'] == {'@email': '', '@phone': ''}

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


class TestApis:
    """Class for Testing all APIs related to the `clientwidget` app
    """

    # Number of users to create
    num_users = 1

    def test_anonymous_user(self, client: APIClient) -> None:
        """Method to test requests from an un-authenticated AnonymousUser

        Args:
            client (APIClient): The client object
        """
        user = auth.get_user(client) # type: ignore
        assert user.is_authenticated == False

        response = client.get('/api/clientwidget/listing')
        assert response.status_code in (401, 403)

        response = client.get('/api/chatbox')
        assert response.status_code in (401, 403)


    @pytest.mark.django_db
    def test_dummy_user(self, client: APIClient) -> None:
        """Method to test requests from a newly registered user

        Args:
            client (APIClient): The client object
        """
        # Create a dummy user
        user = mixer.blend(User)

        client.login(username=user, password='test')
        user = auth.get_user(client) # type: ignore
        assert user.is_authenticated

        response = client.get('/api/clientwidget/listing')
        assert response.status_code == 200

        response = client.get('/api/chatbox')
        assert response.status_code == 200

        data = json.loads(response.content)
        # New user logged in. Must see no bots
        assert len(data) == 0

        response = client.get('/api/auth/logout')
        assert response.status_code == 200 or response.status_code == 201

        client.logout()
    
    
    @pytest.mark.django_db
    def test_chat_listing_api(self, client: APIClient) -> None:
        """Method to test clientwidget listing API

        Args:
            client (APIClient): The client object
        """
        # Create a dummy user
        user = mixer.blend(User)
        bot_owner = user

        client.login(username=user, password='test')
        user = auth.get_user(client) # type: ignore
        assert user.is_authenticated

        web_bot = mixer.blend(Chatbox, title='Website Bot', bot_full_json={}, bot_data_json={'1': {'nodeType': 'INIT'}}, bot_variable_json={}, chatbot_type='website', owner=bot_owner)
        whatsapp_bot = mixer.blend(Chatbox, title='Whatsapp Bot', bot_full_json={}, bot_data_json={'1': {'nodeType': 'INIT'}}, bot_variable_json={}, chatbot_type='whatsapp', owner=bot_owner)

        response = client.get(reverse('client widget bot session', kwargs={'bot_id': web_bot.pk}))
        assert response.status_code == 200
        data = json.loads(response.content)
        wb_room_id, wb_room_name = data['room_id'], data['room_name']

        response = client.get(reverse('client widget bot session', kwargs={'bot_id': whatsapp_bot.pk}))
        assert response.status_code == 200
        data = json.loads(response.content)
        wa_room_id, wa_room_name = data['room_id'], data['room_name']

        response = client.get(reverse('client widget active bots', kwargs={}))
        assert response.status_code == 200

        data = json.loads(response.content)
        assert len(data) == 2

        room_ids = set(bot['room_id'] for bot in data)
        room_names = set(bot['room_name'] for bot in data)
        assert set({wa_room_name, wb_room_name}) == room_names
        assert set({wa_room_id, wb_room_id}) == room_ids

        response = client.get(reverse('client widget active bot type', kwargs={'bot_type': 'website'}))
        assert response.status_code == 200

        data = json.loads(response.content)
        assert len(data) == 1
        assert str(data[0]['bot_id']) == str(web_bot.pk)

        response = client.get(reverse('client widget active bot type', kwargs={'bot_type': 'whatsapp'}))
        assert response.status_code == 200

        data = json.loads(response.content)
        assert len(data) == 1
        assert str(data[0]['bot_id']) == str(whatsapp_bot.pk)

        # Now test deactivation API
        # For the web-based bot
        response = client.post(reverse('client widget deactivate bot', kwargs={'room_name': wb_room_name}), data={}, format="json")
        assert response.status_code == 200

        # Shouldn't be in the listing anymore
        response = client.get(reverse('client widget active bot type', kwargs={'bot_type': 'website'}))
        assert response.status_code == 200

        data = json.loads(response.content)
        assert len(data) == 0

        # For the whatsapp bot
        response = client.post(reverse('client widget deactivate bot', kwargs={'room_name': wa_room_name}), data={}, format="json")
        assert response.status_code == 200

        # Shouldn't be in the listing anymore
        response = client.get(reverse('client widget active bot type', kwargs={'bot_type': 'whatsapp'}))
        assert response.status_code == 200

        data = json.loads(response.content)
        assert len(data) == 0

        # Now complete listing must be empty
        response = client.get(reverse('client widget active bots', kwargs={}))
        assert response.status_code == 200

        data = json.loads(response.content)
        assert len(data) == 0

        client.logout()


    @pytest.mark.django_db
    @pytest.mark.parametrize('populate_db', [{'num_users': num_users}], indirect=True)
    def test_template_chat_api(self, client: APIClient, populate_db: pytest.fixture) -> None:
        """Method to initiate and test a template chat with bots for different users

        Args:
            client (APIClient): The APIClient instance
            populate_db (pytest.fixture): The `populate_db()` fixture, which sets up the DB
        """
        # Now let's test it for the other users which have a bot
        # We'll get them from our `populate_db` setup fixture
        users, bots, variables = populate_db
        for (user, bot_id, variable) in zip(users, bots, variables):
            client.login(username=user, password='test')
            user = auth.get_user(client) # type: ignore
            assert user.is_authenticated

            response = client.get('/api/chatbox')
            assert response.status_code == 200

            data = json.loads(response.content)
            # Has already created a bot during the setup
            assert len(data) == 1 and data[0]['bot_hash'] == bot_id

            # Start a new session for the template chat
            response = client.get(f'/api/clientwidget/session/{bot_id}')
            assert response.status_code == 200

            response_data = json.loads(response.content)
            assert response_data["nodeType"] == "INIT" and response_data["room_name"] is not None and response_data["variables"] == variable

            user_inputs = [] # List of variable inputs per bot session
            variable_dict = dict() # And the corresponding dictionary

            while not ("nodeType" in response_data and response_data["nodeType"] == "END"):              
                # Wait for 2 seconds
                time.sleep(2)
                # Set some flags
                yes_no, multi_choice = False, False
                if "nodeType" in response_data and response_data["nodeType"] == "YES_NO":
                    # If YES / NO button
                    yes_no = True
                    choice = random.choice(["Yes", "No"])
                    for node in response_data["buttons"]:
                        if node["text"] == choice:
                            payload = {'target_id': node['targetId']}
                            payload['post_data'] = choice
                elif "nodeType" in response_data and response_data["nodeType"] == "MULTI_CHOICE":
                    # If Multi choice button
                    multi_choice = True
                    choices = set()
                    for node in response_data["buttons"]:
                        choices.add(node["text"])
                    payload = {'target_id': node['targetId']}
                    payload['post_data'] = random.choice(tuple(choices))
                else:
                    # Try to go to the next target_id node
                    payload = {'target_id': response_data["targetId"]}

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

                response = client.put(f'/api/clientwidget/session/{bot_id}', payload)
                assert response.status_code == 200
                response_data = json.loads(response.content)

            response = client.get('/api/auth/logout')
            assert response.status_code == 200 or response.status_code == 201

            client.logout()
    
    
    @pytest.mark.django_db
    @pytest.mark.parametrize('populate_db', [{'num_users': num_users}], indirect=True)
    def test_chatbot_update_api(self, client: APIClient, populate_db: pytest.fixture) -> None:
        """Method to test the chatbot update APIs. This may cause the variables to be updated, added or deleted.

        Args:
            client (APIClient): The APIClient instance
            populate_db (pytest.fixture): The `populate_db()` fixture, which sets up the DB
        """
        users, bots, variables = populate_db
        for (user, bot_id, variable) in zip(users, bots, variables):
            client.login(username=user, password='test')
            user = auth.get_user(client) # type: ignore
            assert user.is_authenticated

            # Get the current bot data
            response = client.get(f'/api/chatbox/{bot_id}')
            assert response.status_code == 200

            bot_json = json.loads(response.content)
            data = bot_json
            assert 'bot_variable_json' in data and 'bot_lead_json' in data and 'variable_columns' in data

            bot_variable_json, bot_lead_json, variable_columns = data['bot_variable_json'], data['bot_lead_json'], data['variable_columns']
            assert bot_variable_json not in ({}, None) and set(variable_columns) == set(bot_variable_json.keys())

            # Modify the bot, by adding a variable @testvariable1
            bot_variable_json['@testvariable'] = ''
            payload = {
                'bot_variable_json': bot_variable_json,
            }
            response = client.put(f'/api/chatbox/{bot_id}', data=payload, format="json")
            assert response.status_code in (200, 201, 203)

            data = json.loads(response.content)
            bot_json = data
            assert data['bot_variable_json'] == bot_variable_json
            # This variable is not a lead field
            assert '@testvariable' in data['variable_columns'] and '@testvariable' not in data['bot_lead_json']

            # Make a lead variable now
            nodes = bot_json['bot_full_json']['layers'][1]['models']
            lead_variable = None
            for node_id in nodes:
                if 'nodeData' in nodes[node_id] and 'variable' in nodes[node_id]['nodeData']:
                    if 'isLeadField' not in nodes[node_id]['nodeData'] or nodes[node_id]['nodeData']['isLeadField'] == False:
                        # Set it to True
                        lead_variable = nodes[node_id]['nodeData']['variable']
                        bot_json['bot_full_json']['layers'][1]['models'][node_id]['nodeData']['isLeadField'] = True
                        break
            
            # This must not be a lead field previously
            assert lead_variable not in data['bot_lead_json']

            if '@testvariable' in bot_variable_json:
                del bot_variable_json['@testvariable']

            response = client.put(f'/api/chatbox/{bot_id}', data=bot_json, format="json")
            assert response.status_code in (200, 201, 203)
            
            data = json.loads(response.content)
            bot_json = data
            assert data['bot_variable_json'] == bot_variable_json
            # Now it must be a lead field
            assert lead_variable is not None and lead_variable in data['bot_lead_json']
            
            nodes = bot_json['bot_full_json']['layers'][1]['models']
            for node_id in nodes:
                if 'nodeData' in nodes[node_id] and 'variable' in nodes[node_id]['nodeData']:
                    if nodes[node_id]['nodeData']['variable'] == lead_variable:
                        # Let's now update this lead_variable
                        old_lead_variable = lead_variable
                        lead_variable = '@leadvariableupdated'
                        bot_json['bot_full_json']['layers'][1]['models'][node_id]['nodeData']['variable'] = lead_variable
                        break
            
            response = client.put(f'/api/chatbox/{bot_id}', data=bot_json, format="json")
            assert response.status_code in (200, 201, 203)

            data = json.loads(response.content)
            updated_variables = set(list(bot_variable_json.keys()) + [lead_variable]) - {old_lead_variable}
            assert set(data['bot_variable_json'].keys()) == updated_variables
            assert set(data['bot_lead_json']) == set(list(bot_lead_json.keys()) + [lead_variable]) - {old_lead_variable}            


    @pytest.mark.django_db
    @pytest.mark.parametrize('populate_db', [{'num_users': num_users}], indirect=True)
    def test_operator_assign_api(self, client: APIClient, populate_db: pytest.fixture) -> None:
        """Method to test the assignment of operators to chats by an admin manager

        Args:
            client (APIClient): The APIClient instance
            populate_db (pytest.fixture): The `populate_db()` fixture, which sets up the DB
        """
        # Now let's test it for the other users which have a bot
        # We'll get them from our `populate_db` setup fixture
        users, bots, variables = populate_db
        
        # Create our Admin User for assigning operators
        admin = mixer.blend(User, role='AM')

        # Create a dummy operator
        operator = mixer.blend(User, email="operator@example.com", role='AO')

        admin_operator = APIClient()
        admin_operator.login(username=admin, password='test')
        user = auth.get_user(admin_operator) # type: ignore
        assert user.is_authenticated and user.role == 'AM'
        
        for (user, bot_id, _) in zip(users, bots, variables):
            client.login(username=user, password='test')
            user = auth.get_user(client) # type: ignore
            assert user.is_authenticated

            # Start a new session for the template chat
            response = client.get(f'/api/clientwidget/session/{bot_id}')
            assert response.status_code == 200

            data = json.loads(response.content)
            room_id, room_name = data['room_id'], data['room_name']

            response = admin_operator.post(reverse('operator_assignment'), data={"operator_id": operator.email, "room_name": room_name}, format="json")
            assert response.status_code == 200

            instance = ChatAssign.objects.get(room_id__room_id=room_id)
            assert instance.room_id.room_name == room_name and operator in instance.operators.all()

            client.logout()
        
        admin_operator.logout()
