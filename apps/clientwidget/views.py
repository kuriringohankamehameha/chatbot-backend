import uuid

import requests
from decouple import UndefinedValueError, config
from django.apps import apps
from django.shortcuts import render

Chatbox = apps.get_model(app_label='chatbox', model_name='Chatbox')
ChatRoom = apps.get_model(app_label='clientwidget', model_name='ChatRoom')
shared_client = requests.Session() # Shared anonymous user client

try:
    server_addr = str(config('serverhost'))
except UndefinedValueError:
    server_addr = 'http://127.0.0.1:8000'


try:
    SESSION_TIMEOUT_HOURS = float(config('SESSION_TIMEOUT_HOURS'))
    lock_timeout = int(round(SESSION_TIMEOUT_HOURS * 60 * 60))
except UndefinedValueError:
    # Default is 6 hours
    lock_timeout = int(6 * 60 * 60)


# Assign some buffer time for the preservation of important data
try:
    BUFFER_TIME = int(round(config('SESSION_BUFFER_TIME')))
except UndefinedValueError:
    BUFFER_TIME = 150 # Set to 150 seconds


# Set maximum timeout for webhook component
try:
    WEBHOOK_TIMEOUT = float(config('WEBHOOK_TIMEOUT'))
except:
    WEBHOOK_TIMEOUT = 20 # Default is 20 seconds


# Create your views here.
def index(request):
    return render(request, 'clientwidget_updated/index.html', {})

def room(request, owner_id, room_id):    
    queryset = ChatRoom.objects.filter(room_id=room_id)
    if queryset.count() > 0 and Chatbox.objects.filter(owner__uuid=owner_id) is not None:
        return render(request, 'clientwidget_updated/room.html', {
            'room_id': str(room_id),
            'owner_id': str(owner_id),
        })
    else:
        return render(request, 'clientwidget_updated/404_not_found.html', {'room_id': str(room_id), 'owner_id': str(owner_id)})

def adminroom(request, owner_id):
    if request.user.is_authenticated and request.user.is_superuser:
        admin = True
    else:
        admin = False

    context = { 'owner_id' : owner_id, 'admin': admin }
    return render(request, 'clientwidget_updated/admin_room.html', context)

def operatorroom(request, owner_id, operator_id):
    context = { 'owner_id' : owner_id, 'operator_id': operator_id }
    return render(request, 'clientwidget_updated/operator.html', context)

def polling(request, owner_id):
    if not request.user.is_authenticated:
        return render(request, 'clientwidget_updated/404_not_found.html', {'room_id': 'Unauthorized', 'owner_id': 'User'})
    
    queryset = Chatbox.objects.filter(owner__uuid=owner_id)
    if queryset.count() > 0:
        return render(request, 'clientwidget_updated/polling.html', {
            'owner_id': str(owner_id),
        })
    else:
        return render(request, 'clientwidget_updated/404_not_found.html', {'room_id': 'No such owner', 'owner_id': 'has bots'})

def listing(request, owner_id):
    if not request.user.is_authenticated:
        return render(request, 'clientwidget_updated/404_not_found.html', {'room_id': 'Unauthorized', 'owner_id': 'User'})
    
    queryset = Chatbox.objects.filter(owner__uuid=owner_id)
    if queryset.count() > 0:
        return render(request, 'clientwidget_updated/listing.html', {
            'owner_id': str(owner_id),
        })
    else:
        return render(request, 'clientwidget_updated/404_not_found.html', {'room_id': 'No such owner', 'owner_id': 'has bots'})