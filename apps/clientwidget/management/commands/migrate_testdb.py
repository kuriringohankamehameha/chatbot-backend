import os

from decouple import Config, RepositoryEnv
from django.conf import settings
from django.core import management
from django.core.management.base import BaseCommand

DOTENV_FILE = os.path.join(os.getcwd(), 'chatbot', '.env')
config = Config(RepositoryEnv(DOTENV_FILE))


class Command(BaseCommand):
    help = 'Cleanup Existing Chat Sessions from Redis and Dump them into DB'

    def handle(self, *args, **options):
        settings.DATABASES = {
            'default': {
                'ENGINE': 'django.db.backends.postgresql_psycopg2',
                'NAME': 'test_' + config.get('DB_NAME_PSQL'),
                'USER': config.get('DB_USER_PSQL'),
                'PASSWORD': config.get('DB_PASSWORD_PSQL'),
                'HOST': config.get('DB_HOST_PSQL'),
                'PORT': config.get('DB_PORT_PSQL'),
            },   
            'secondary': {
                'ENGINE': 'django.db.backends.postgresql_psycopg2',
                'NAME': 'test_' + config.get('DB_NAME_PSQL'),
                'USER': config.get('DB_USER_PSQL'),
                'PASSWORD': config.get('DB_PASSWORD_PSQL'),
                'HOST': config.get('DB_HOST_PSQL'),
                'PORT': config.get('DB_PORT_PSQL'),
            },
        }
        management.call_command('migrate')
        print('Successfully migrated the test DB!')
