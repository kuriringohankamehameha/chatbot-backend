from django.apps import AppConfig

import os
from decouple import Config, RepositoryEnv, UndefinedValueError


class ClientwidgetConfig(AppConfig):
    name = 'clientwidget'
