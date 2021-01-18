from __future__ import unicode_literals

import uuid
from django.db import models
from django.core.mail import send_mail
from django.contrib.auth.models import PermissionsMixin
from django.contrib.auth.base_user import AbstractBaseUser
from django.utils.translation import ugettext_lazy as _

from .managers import UserManager
from django.conf import settings


class CustomerUser(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(_('email address'), unique=True)
    api_base_url = models.CharField(_('api base url'), max_length=100)
    client_id = models.UUIDField(_('client id'), default=uuid.uuid4)
    client_secret = models.UUIDField(_('client secret'), default=uuid.uuid4)
