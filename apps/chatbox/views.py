from .models import Chatbox
from .serializers import ChatboxListSerializer
from rest_framework import generics, permissions
from django.http import Http404
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated

import os
from itertools import zip_longest
from threading import Event # Wait for an event to occur

from django.shortcuts import render
from django.db import transaction, IntegrityError
from django.template.response import TemplateResponse

from decouple import Config, RepositoryEnv, UndefinedValueError

from .serializers import ChatBoxMessageSerializer
from .models import ChatRoom

async_mode = None

class ChatboxList(APIView):

    permission_classes = [IsAuthenticated]

    def get(self, request, format=None):
        queryset = Chatbox.objects.filter(owner=self.request.user)
        serializer = ChatboxListSerializer(queryset, many=True)
        return Response(serializer.data)

    def post(self, request, format=None):
        serializer = ChatboxListSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(owner=self.request.user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


def index(request):
    #global thread
    #if thread is None:
    #    thread = sio.start_background_task(background_handler)
    return render(request, 'chatbox/index.html', {})


def room(request, room_name):
    queryset = ChatRoom.objects.filter(room_name=room_name)
    if queryset.count() > 0:
        return render(request, 'chatbox/room.html', {
            'room_name': room_name
        })
    else:
        return TemplateResponse(request, 'chatbox/404_not_found.html', {'room_name': room_name})


def adminroom(request, room_name):
    if request.user.is_authenticated and request.user.is_superuser:
        admin = True
    else:
        admin = False

    context = { 'room_name' : room_name, 'admin': admin }
    return render(request, 'chatbox/admin_room.html', context)


def get_user():
    # TODO: Get the user name for the session info from the client
    return 'AnonymousUser'
