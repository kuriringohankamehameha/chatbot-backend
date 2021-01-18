import pytest
import os
from decouple import Config, RepositoryEnv, UndefinedValueError
from django.conf import settings

DOTENV_FILE = os.path.join(os.getcwd(), 'chatbot', '.env')
env_config = Config(RepositoryEnv(DOTENV_FILE))

os.environ['DJANGO_SETTINGS_MODULE'] = 'chatbot.settings'

@pytest.fixture(scope="session", autouse=True)
def setup():
    # Faster password hashing for authenticating large no of users
    settings.PASSWORD_HASHERS = [
        'django.contrib.auth.hashers.MD5PasswordHasher',
    ]
