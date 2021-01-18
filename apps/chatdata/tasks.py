import csv
import datetime
import io
import json
import os
import uuid

import xlsxwriter
from celery import Celery, shared_task, task
from decouple import Config, RepositoryEnv, UndefinedValueError
from django.apps import apps
from django.core.cache import cache
from django.db import transaction
from django.http import HttpResponse

from .utils import export_chat_data

Chatbox = apps.get_model(app_label='chatbox', model_name='Chatbox')
ChatRoom = apps.get_model(app_label='clientwidget', model_name='ChatRoom')

@shared_task
def export_chat_data_task(request, bot_id: uuid.UUID, fields: tuple, fmt: str) -> HttpResponse:
    """Exports the chat data by converting it into a particular format

    Args:
        request: The http request
        bot_id (uuid.UUID): The bot ID
        fields (tuple): A tuple of all the necessary fields (column names)
        fmt (str): The format of the output file (.csv, .xlsx, .pdf)

    Returns:
        HttpResponse: A Http Response object
    """
    return export_chat_data(request, bot_id, fields, fmt)
