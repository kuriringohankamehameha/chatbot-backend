from django.apps import AppConfig

import os
from decouple import Config, RepositoryEnv, UndefinedValueError
from redis import StrictRedis

# Redis Server Options
DOTENV_FILE = os.path.join(os.getcwd(), 'chatbot', '.env')
env_config = Config(RepositoryEnv(DOTENV_FILE))

HOST = env_config.get('REDIS_SERVER_HOST')

try:
    PASSWORD = env_config.get('REDIS_SERVER_PASSWORD')
except UndefinedValueError:
    PASSWORD = None

PORT = env_config.get('REDIS_SERVER_PORT')

if PASSWORD is None:
    REDIS_CONNECTION = StrictRedis(host=HOST, port=PORT)
else:
    REDIS_CONNECTION = StrictRedis(host=HOST, password=PASSWORD, port=PORT)

try:
    CHATBOX_DEMO_APPLICATION = env_config.get('CHATBOX_DEMO_APPLICATION', cast=bool)
except UndefinedValueError:
    CHATBOX_DEMO_APPLICATION = False

try:
    USE_CELERY = env_config.get('USE_CELERY', cast=bool)
except UndefinedValueError:
    USE_CELERY = False

class ChatboxConfig(AppConfig):
    name = 'chatbox'

    # def ready(self):
    #     from chatbox import handlers
