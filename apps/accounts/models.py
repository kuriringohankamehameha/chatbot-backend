from __future__ import unicode_literals

import uuid
from django.db import models
from django.core.mail import send_mail
from django.contrib.auth.models import PermissionsMixin
from django.contrib.auth.base_user import AbstractBaseUser
from django.utils.translation import ugettext_lazy as _
from .managers import UserManager
from django.conf import settings

class Teams(models.Model):
    name = models.CharField(_('name'), max_length=100, blank=True)
    description = models.TextField(_('description'), max_length=100, blank=True)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="group_owner", on_delete=models.CASCADE)
    


class User(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(_('email address'), unique=True)
    first_name = models.CharField(_('first name'), max_length=100, blank=True)
    last_name = models.CharField(_('last name'), max_length=100, blank=True)
    is_active = models.BooleanField(_('active'), default=True)
    is_staff = models.BooleanField(_('staff'), default=False) 
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='user_created_by', blank=True, null=True)
    created_on = models.DateTimeField(_('user created on'), auto_now_add=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='user_updated_by', blank=True, null=True)
    updated_on = models.DateTimeField(_('user updated on'), auto_now=True)
    user_is_deleted = models.BooleanField(default=False)
    user_deleted_at = models.DateTimeField(blank=True, null=True)

    operator_of = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='user_operator_of', null=True, blank=True)
    
    operator_owner = models.UUIDField(null=True, blank=True)

    operator_status = models.BooleanField(default=False)

    team_member = models.ForeignKey(Teams, on_delete=models.CASCADE, related_name='team_member_of', null=True, blank=True)

    phone_number = models.CharField(max_length=30, blank=True, null=True)
    avatar = models.ImageField(upload_to='user_avatars/', null=True, blank=True)
    website = models.CharField(_('user website name'), max_length=250, blank=True)
    address = models.CharField(_('user address'), max_length=500, blank=True)
    city = models.CharField(_('user city'), max_length=250, blank=True)
    state = models.CharField(_('user state'), max_length=250, blank=True)
    zipcode = models.CharField(_('user zipcode'), max_length=250, blank=True)
    country = models.CharField(_('user country'), max_length=250, blank=True)
    paid = models.BooleanField(default=False)
    google_granted_acc = models.EmailField(null=True, blank=True)
    role_select = (
        ('SA','Super Admin'),
        ('SAO','Super Admin operator'),
        ('AM','Admin master'),
        ('AO','Admin operator')
    )
    ext_db_label = models.CharField(max_length=25, null=True, default='default')
    role = models.CharField(max_length=3, choices=role_select)
    utc_offset = models.IntegerField(default=0)
    can_takeover = models.BooleanField(default=False)
    acc_version = models.CharField(max_length=10, default='')
    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    class Meta:
        verbose_name = _('user')
        verbose_name_plural = _('users')

    def get_full_name(self):
        '''
        Returns the first_name plus the last_name, with a space in between.
        '''
        full_name = '%s %s' % (self.first_name, self.last_name)
        return full_name.strip()

    def get_short_name(self):
        '''
        Returns the short name for the user.
        '''
        return self.first_name

    def email_user(self, subject, message, from_email=None, **kwargs):
        '''
        Sends an email to this User.
        '''
        send_mail(subject, message, from_email, [self.email], **kwargs) 


