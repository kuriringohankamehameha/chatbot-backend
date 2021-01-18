import os
from decouple import config
from django.core.exceptions import ImproperlyConfigured

# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    from ..sentry_settings import *
except Exception as e:
    print('sentry file not avaiable')

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/2.2/howto/deployment/checklist/


# Application definition

DEFAULT_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
]

THIRD_PARTY_APPS =[
    # add apps which you install using pip
    'corsheaders',
    'rest_framework',
    'django_rest_passwordreset',
    'channels',
    'drf_yasg',
    'django_jsonfield_backport',
]

LOCAL_APPS =[
    # add local apps which you create using startapp
    'apps.accounts',
    'apps.chatdata',
    'apps.clientwidget',
    'apps.chatbox',
    'apps.permission',
    'apps.taskscheduler.apps.TaskschedulerConfig',
]

# Application definition
INSTALLED_APPS = DEFAULT_APPS + THIRD_PARTY_APPS + LOCAL_APPS


# AbstractBaseUser Model
AUTH_USER_MODEL = 'accounts.User' 

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    # 'apps.chatbox.middlewares.BlockNonOwner',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    # 'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'chatbot.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, '../frontend')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'chatbot.wsgi.application'

ASGI_APPLICATION = "chatbot.routing.application"

# Password validation
# https://docs.djangoproject.com/en/2.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/2.2/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'
SCHED_TIME_ZONE = 'Asia/Calcutta'

USE_I18N = True

USE_L10N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/2.2/howto/static-files/

STATIC_URL = '/static/'

# MEDIA SETTINGS (Not for Production)
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, '../../media/')

# Add these new lines
STATICFILES_DIRS = [
    os.path.join(BASE_DIR, '../frontend/admin/build/static/'),
    os.path.join(BASE_DIR, '../frontend/superadmin/build/static/'),
    os.path.join(BASE_DIR, '../frontend/clientwidget/build/static/'),
    os.path.join(BASE_DIR, 'staticfiles')
]
# STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')

# X_FRAME for CLient Widget
X_FRAME_OPTIONS = 'SAMEORIGIN'

# Loading database
try:
    from .database import *
except ImportError:
    raise ImproperlyConfigured("No database file")