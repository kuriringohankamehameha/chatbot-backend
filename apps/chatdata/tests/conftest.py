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
from django.contrib import auth
from django.core import management
from mixer.backend.django import mixer
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.chatbox.models import Chatbox
from apps.clientwidget.models import ChatRoom


@mixer.middleware(User)
def encrypt_password(user: 'User') -> 'User':
    user.set_password('test')
    return user


@pytest.fixture
def client() -> APIClient:
    return APIClient()


@pytest.fixture
def setup_db_chatdata(request) -> Iterator[Tuple[List[User], List[str], List[dict], List[List[str]], List[List[dict]]]]:
    """Sets up the Database with example data for the template Chatbot flow.

    Yields:
        Iterator[Tuple[List[User], List[str], List[dict], List[List[str]], List[List[dict]]]]: An iterator of (`User`s, `bot_id`s, `variable`s, `room`s and `user_input`s)
    """
    print('Setup')
    # Create Users
    NUM_USERS = request.param['num_users']
    NUM_ROOMS_PER_USER = request.param['rooms_per_user']
    users = mixer.cycle(NUM_USERS).blend(User, is_superuser=True)
    bots = [] # Assume one bot per user
    variables = [] # Variables per bot

    client = APIClient()

    # File information
    curr_file = str(os.getenv('PYTEST_CURRENT_TEST'))
    curr_file = curr_file.split('::')[0]
    curr_dir = '/'.join(curr_file.split('/')[:-1])
    app_dir = '/'.join(curr_file.split('/')[:-3])

    bot_dir = os.path.join(app_dir, 'clientwidget', 'tests', 'bots')
    bot_files = sorted(glob.glob(os.path.join(bot_dir, 'test_*.json')))
    variable_files = sorted(glob.glob(os.path.join(bot_dir, 'variables_*.json')))

    rooms: List[List[str]]
    rooms = [] # Each user has some rooms per bot, so this is a list of lists

    users_inputs: List[List[dict]]
    users_inputs = []

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

        # Create some rooms
        # Let's take 2 rooms per user
        rooms.append([])
        users_inputs.append([])
        for _ in range(NUM_ROOMS_PER_USER):
            length = 10
            room_name = ''.join(random.choice(string.ascii_letters) for i in range(length))
            rooms[-1].append(room_name)

            variable_json = dict()

            # Now add some sample messages
            for key in bot_variable_json:
                name = ''.join(random.choice(string.ascii_letters) for _ in range(4))
                variable_json[key] = name

            messages = [{"user": "end_user", "message": f"Test message - {room_name}"}]
            # Create the instance
            instance = ChatRoom.objects.create(room_name=room_name, bot_id=uuid.UUID(bot_hash), variables=variable_json, messages=messages)
            assert instance.room_name == room_name

            users_inputs[-1].append(variable_json)

        # Logout
        response = client.get('/api/auth/logout')
        assert response.status_code == 200 or response.status_code == 201
        client.logout()
    
    assert len(users) == len(bots)

    yield (users, bots, variables, rooms, users_inputs)
    
    print("Teardown")
    
    # Clear all sessions
    management.call_command('clear_sessions')


@pytest.fixture
def setup_dummy_bots(request) -> Iterator[Tuple[User, List[dict], List[dict]]]:
    """Sets up some dummy Chatbots with incorrect fields for testing

    Yields:
        Iterator[Tuple[User, List[dict], List[dict]]]: An iterator of (`User`, `bot_id`s, `variable`s)
    """
    print('Setup')

    variables: List[dict]
    variables = [] # Variables per bot

    client = APIClient()

    bots = []
    num_bots = 0

    # File information
    curr_file = str(os.getenv('PYTEST_CURRENT_TEST'))
    curr_file = curr_file.split('::')[0]
    curr_dir = '/'.join(curr_file.split('/')[:-1])
    app_dir = '/'.join(curr_file.split('/')[:-3])

    bot_dir = os.path.join(app_dir, 'clientwidget', 'tests', 'bots')
    bot_files = sorted(glob.glob(os.path.join(bot_dir, 'test_*.json')))
    variable_files = sorted(glob.glob(os.path.join(bot_dir, 'variables_*.json')))

    # Create a dummy user
    user = mixer.blend(User)
    
    # Login first
    client.login(username=user, password='test')
    _user = auth.get_user(client) # type: ignore
    assert _user.is_authenticated

    # Now make an incorrect bot
    bot_json = {
        "title": "Test Empty Bot",
        "publish_status": False,
    }
    
    response = client.post('/api/chatbox', data=bot_json, format="json")
    assert response.status_code == 200 or response.status_code == 201

    data = json.loads(response.content)
    bot_hash = data['bot_hash']
    assert bot_hash is not None

    # Add to the list of bots
    bots.append({bot_hash: "Test Empty Bot"})

    # Don't add the `bot_full_json`. Let it be NULL
    #bot_json = {
    #    'bot_full_json': None,
    #}
    # Presently, parse_json() doesn't work on `None` / {} input
    #response = client.put(f'/api/chatbox/{bot_hash}', data=bot_json, format="json")
    # Bad request
    #assert response.status_code == 400

    # Check the json
    #data = json.loads(response.content)
    #assert 'bot_data_json' in data and 'bot_variable_json' in data
    
    #bot_data_json, bot_variable_json = data['bot_data_json'], data['bot_variable_json']
    # Both data and variables must be empty
    #assert (bot_data_json is None or bot_data_json == {}) and (bot_variable_json is None or bot_variable_json == {})

    # Empty variables
    instance = Chatbox.objects.get(pk=uuid.UUID(bot_hash))
    assert instance.bot_variable_json in ({}, None)
    variables.append(instance.bot_variable_json)

    # Add another useless bot
    bot_json = {
        "title": "Test Useless Bot",
        "publish_status": False,
    }
    
    response = client.post('/api/chatbox', data=bot_json, format="json")
    assert response.status_code == 200 or response.status_code == 201

    num_bots += 1

    data = json.loads(response.content)
    bot_hash = data['bot_hash']
    assert bot_hash is not None

    # Add to the list of bots
    bots.append({bot_hash: "Test Useless Bot"})

    with open(random.choice(bot_files), 'r') as f:
        bot_json = json.load(f)

    response = client.put(f'/api/chatbox/{bot_hash}', data=bot_json, format="json")
    assert response.status_code in (200, 201)

    num_bots += 1
    variable_json = json.loads(response.content)['bot_variable_json']

    variables.append(variable_json)

    instance = ChatRoom.objects.create(
        room_name="Test Useless Bot", bot_id=uuid.UUID(bot_hash),
        variables={},
    )

    response = client.get('/api/chatbox')
    assert response.status_code == 200

    data = json.loads(response.content)
    assert len(data) == num_bots

    client.logout()

    yield (user, bots, variables)

    print('Teardown')

    # Clear all sessions
    management.call_command('clear_sessions')


@pytest.fixture
def setup_chatdata(request) -> Iterator[Tuple[User, List[dict], List[dict], List[str]]]:
    """Sets up some dummy Chatbots with incorrect fields for testing

    Yields:
        Iterator[Tuple[User, List[dict], List[dict], List[str]]]: An iterator of (`User`, `bot_id`s, `variable`s and `room`s)
    """
    print('Setup')

    bot_variables: List[dict]
    bot_variables = [] # Variables for the bot
    rooms = [] # List of rooms for that bot

    client = APIClient()

    bots = []
    num_bots = 0
    num_chats = 10 # We'll simulate 10 chats

    # File information
    curr_file = str(os.getenv('PYTEST_CURRENT_TEST'))
    curr_file = curr_file.split('::')[0]
    curr_dir = '/'.join(curr_file.split('/')[:-1])
    app_dir = '/'.join(curr_file.split('/')[:-3])

    bot_dir = os.path.join(app_dir, 'clientwidget', 'tests', 'bots')
    bot_files = sorted(glob.glob(os.path.join(bot_dir, 'test_lead*.json')))
    variable_files = sorted(glob.glob(os.path.join(bot_dir, 'variables_lead*.json')))

    # Create a dummy user
    user = mixer.blend(User)
    
    # Login first
    client.login(username=user, password='test')
    _user = auth.get_user(client) # type: ignore
    assert _user.is_authenticated

    # Now make an incorrect bot
    bot_json = {
        "title": "Test Bot",
        "publish_status": False,
    }
    
    response = client.post('/api/chatbox', data=bot_json, format="json")
    assert response.status_code == 200 or response.status_code == 201

    data = json.loads(response.content)
    bot_hash = data['bot_hash']
    assert bot_hash is not None

    # Add to the list of bots
    bots.append({bot_hash: "Test Bot"})
    
    num_bots += 1

    with open(random.choice(bot_files), 'r') as f:
        bot_json = json.load(f)
    
    bot_json['title'] = 'Test Bot' # Change Title

    response = client.put(f'/api/chatbox/{bot_hash}', data=bot_json, format="json")
    assert response.status_code in (200, 201)

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

    variable_json = json.loads(response.content)['bot_variable_json']
    assert variable_json not in ({}, None)

    instance = Chatbox.objects.get(pk=uuid.UUID(bot_hash))
    assert instance.bot_variable_json not in ({}, None)

    bot_instance = Chatbox.objects.get(pk=uuid.UUID(bot_hash))

    # Let's simulate some chats
    for _ in range(num_chats):
        room_name = ''.join(random.choice(string.ascii_uppercase) for _ in range(8))
        populated_variables = {}
        for name in bot_instance.bot_variable_json:
            value = ''.join(random.choice(string.ascii_letters) for _ in range(5))
            populated_variables[name] = value
        rooms.append(room_name)
        bot_variables.append(populated_variables)
        
        # Create the instance immediately. Otherwise, may cause re-ordering
        instance = ChatRoom.objects.create(
            room_name=room_name, bot_id=uuid.UUID(bot_hash),
            variables=populated_variables, bot_is_active=True, bot_info=bot_instance,
        )
        instance.save() # Force Save to avoid potential re-ordering

    assert len(rooms) == num_chats

    response = client.get('/api/chatbox')
    assert response.status_code == 200

    data = json.loads(response.content)
    assert len(data) == num_bots

    # Let's see the number of active sessions
    response = client.get('/api/clientwidget/listing')
    assert response.status_code == 200
    data = json.loads(response.content)
    assert len(data) == num_chats

    # Get the list of variables
    bot_variables = list(chat['variables'] for chat in data)

    # Let's deactivate all chats
    for sess in data:
        room_name = sess['room_name']
        response = client.post(f'/api/clientwidget/deactivate/{room_name}')
        assert response.status_code == 200
    
    # Now the number of active sessions must be zero
    response = client.get('/api/clientwidget/listing')
    data = json.loads(response.content)
    assert len(data) == 0

    client.logout()

    yield (user, bots, bot_variables, rooms)

    print('Teardown')

    # Clear all sessions
    management.call_command('clear_sessions')
