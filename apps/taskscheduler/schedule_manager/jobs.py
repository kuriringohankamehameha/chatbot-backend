import csv
import io
import traceback
from datetime import datetime, timedelta

from apps.accounts.models import User
from apps.clientwidget.events import cleanup_room_redis
from apps.clientwidget.exceptions import create_logger
from apps.clientwidget.views import BUFFER_TIME, lock_timeout
from apps.clientwidget.consumers import ClientWidgetConsumer
from decouple import UndefinedValueError, config
from django.apps import apps
from django.conf import settings
from django.core.cache import cache
from django.core.mail import EmailMessage, get_connection, send_mail
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.encoding import force_bytes, force_text
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

Chatbox = apps.get_model(app_label='chatbox', model_name='Chatbox')
ChatRoom = apps.get_model(app_label='clientwidget', model_name='ChatRoom')
ChatSession = apps.get_model(app_label='clientwidget', model_name='ChatSession')

logger = create_logger(__name__)

try:
    from chatbot.database import DATABASES
    databases = [database for database in DATABASES]
except ImportError:
    # Only default label
    databases = ["default"]


def is_child(jobid):
    if cache.get(f"apscheduler_{jobid}", False) == False:
        cache.set(f"apscheduler_{jobid}", True, timeout=5*60)
        return False
    else:
        logger.info(f"Child worker. Master worker already started")
        return True


class ClientWidgetJobs():

    @staticmethod
    def send_dummy_email(jobid=1):
        if cache.get(f"apscheduler_{jobid}", False) == False:
            cache.set(f"apscheduler_{jobid}", True, timeout=5*60)
        else:
            logger.info(f"Child worker. Master worker already started")
            return
        
        logger.info("Sending Clientwidget dummy emails")

        mail_subject = "ClientWidget Test Mail"
        from_email = config('EMAIL_HOST_USER')
        
        admin_users = User.objects.filter(role='AM')

        for admin_user in admin_users:
            try:
                to_email = [admin_user.email]
                if to_email == []:
                    continue

                bot_list = Chatbox.objects.filter(owner=admin_user, subscription_type__in=('cron', 'all',))

                if len(bot_list) == 0:
                    continue

                message = 'This is a test email. Pls ignore'

                email = EmailMessage(mail_subject, message, from_email=from_email, to=to_email)
                
                email.send()
            except:
                traceback.print_exc()
                logger.critical(f"Error sending mail to admin {admin_user.email}")

        logger.info("Scheduled mails are sent")


    @staticmethod
    def chatsession_update(jobid=2):
        # Getting a list of Dicts so as to iterate safely while deleting
        if (is_child(jobid) == True):
            return
        
        sessions = ChatSession.objects.exclude(updated_on__range=[timezone.now()-timezone.timedelta(seconds=24 * 60 * 60 + BUFFER_TIME), timezone.now()]).values()
        
        logger.info("Performing the Cron session update for Clientwidget")
        
        for db_label in databases:
            for session in sessions:
                room_id = session['room_id']
                room_name = session['room_name']

                logger.info(f"Room Id = {room_id}, room_name = {room_name}")
                
                queryset = ChatRoom.objects.using(db_label).filter(room_id = room_id)

                if room_name is not None and len(queryset) > 0:
                    instance = queryset.first()
                    if instance.bot_is_active == True and cache.get(f"CLIENTWIDGET_EXPIRY_LOCK_{room_name}") is not None:
                        # We have some websocket connections pending possibly
                        # Force Disconnect them
                        logger.info(f"Disconnecting Websocket Connections on Room - {room_name}")
                        # ClientWidgetConsumer.send_from_api('Session Timeout', room_name, bot_type='website', user='session_timeout')
                        logger.info("Successfully Disconnected the connection!")
                
                if room_name is not None:
                    is_lead = cache.get(f"IS_LEAD_{room_name}")
                    if is_lead is not None:
                        queryset.update(bot_is_active = False, is_lead = is_lead)
                    else:
                        queryset.update(bot_is_active = False)
                    
                    cleanup_room_redis(room_name, reset_count=True, bot_type='website')

                    # Now finally force delete all the cache keys
                    cache.delete(f'CLIENTWIDGETLEADFIELDS_{room_id}')
                    cache.delete(f"CLIENTWIDGETLEADDATA_{room_id}")
                    cache.delete(f'CLIENTWIDGETROOMINFO_{room_id}')
                    cache.delete(f'IS_LEAD_{room_id}')
                    cache.delete(f"CLIENTWIDGETSUBSCRIBED_{room_id}")
                    cache.delete(f"CLIENTWIDGETTIMEOUT_{room_id}")
                    cache.delete(f"CLIENTWIDGET_SESSION_TOKEN_{room_id}")
                    cache.delete(f"CLIENTWIDGET_EXPIRY_LOCK_{room_id}")
                else:
                    # Worst case - Just update bot status
                    queryset.update(bot_is_active = False)
                
                ChatSession.objects.using(db_label).filter(room_id = room_id).delete() # delete the session


    @staticmethod
    def clientwidget_session_update(jobid=3):
        # TODO: Get the set of all db_labels across all owners and update all of them
        if (is_child(jobid) == True):
            return
        
        for db_label in databases:
            sessions = ChatRoom.objects.using(db_label).filter(chatbot_type='website', bot_is_active=True).exclude(updated_on__range=[timezone.now()-timezone.timedelta(seconds=lock_timeout + BUFFER_TIME), timezone.now()])
            
            logger.info("Performing the Cron session update for Clientwidget")
            
            for session in sessions:
                room_id = session.room_id
                room_name = session.room_name
                

                logger.info(f"Room Id = {room_id}, room_name = {room_name}")
                
                if session.bot_is_active == True and cache.get(f"CLIENTWIDGET_EXPIRY_LOCK_{room_id}") is not None:
                    # We have some websocket connections pending possibly
                    # Force Disconnect them
                    logger.info(f"Disconnecting Websocket Connections on Room - {room_id}")
                    # ClientWidgetConsumer.send_from_api('Session Timeout', str(room_id), bot_type='website')       owner_id argument
                    logger.info("Successfully Disconnected the connection!")
                
                if room_id is not None:
                    is_lead = cache.get(f"IS_LEAD_{room_id}")
                    if is_lead is not None:
                        session.bot_is_active = False
                        session.is_lead = is_lead
                    else:
                        session.bot_is_active = False
                    
                    session.end_time = datetime.utcnow()

                    session.save(using=db_label)
                    
                    cleanup_room_redis(room_id, reset_count=True, bot_type='website')

                    # Now finally force delete all the cache keys
                    cache.delete(f'CLIENTWIDGETLEADFIELDS_{room_id}')
                    cache.delete(f"CLIENTWIDGETLEADDATA_{room_id}")
                    cache.delete(f'CLIENTWIDGETROOMINFO_{room_id}')
                    cache.delete(f'IS_LEAD_{room_id}')
                    cache.delete(f"CLIENTWIDGETSUBSCRIBED_{room_id}")
                    cache.delete(f"CLIENTWIDGETTIMEOUT_{room_id}")
                    cache.delete(f"CLIENTWIDGET_SESSION_TOKEN_{room_id}")
                    cache.delete(f"CLIENTWIDGET_EXPIRY_LOCK_{room_id}")


    @staticmethod
    def clientwidget_send_email(jobid=4):
        if cache.get(f"apscheduler_{jobid}", False) == False:
            cache.set(f"apscheduler_{jobid}", True, timeout=5*60)
        else:
            logger.info(f"Child worker. Master worker already started")
            return
        
        logger.info("Sending Clientwidget Lead emails to subcscribed admin users")

        mail_subject = "Clientwidget Lead Update"
        from_email = config('EMAIL_HOST_USER')
        
        admin_users = User.objects.filter(role='AM')

        export_only_leads = True

        for admin_user in admin_users:
            try:
                to_email = [admin_user.email]
                if to_email == []:
                    continue

                offset = admin_user.utc_offset

                bot_list = Chatbox.objects.filter(owner=admin_user, subscription_type__in=('cron', 'all',))

                if len(bot_list) == 0:
                    continue

                num_files = 0

                message = render_to_string('send_lead_update_email.html', {'user': admin_user})

                email = EmailMessage(mail_subject, message, from_email=from_email, to=to_email)
                
                fields = [field.get_attname_column()[1] for field in ChatRoom._meta.fields if field.get_attname_column()[1] not in ['room_id', 'variables', 'bot_info', 'recent_messages', 'messages', 'bot_id', 'assignment_type']]

                lead_fields = ['visitor_id', 'room_name', 'created_on', 'updated_on', 'end_time', 'channel_id']

                if export_only_leads == True:
                    fields = lead_fields
                
                for bot in bot_list:
                    _fields = fields
                    
                    if export_only_leads == True:
                        _fields = list(bot.bot_lead_json.keys()) + _fields
                    else:
                        _fields = bot.variable_columns + _fields
                    
                    curr_time = timezone.now() + timedelta(minutes=offset)

                    end_date = timezone.now()
                    start_date = end_date - timedelta(days=1)
                    
                    queryset = ChatRoom.objects.using(bot.owner.ext_db_label).filter(bot_id=bot.bot_hash, updated_on__range=[start_date, end_date]).order_by('-updated_on', '-created_on')
                    
                    if not queryset:
                        # Don't send any update, since it's empty
                        continue
                    
                    file_name = f"Leads_{bot.title}_{curr_time}"
                    file_name = file_name.replace('"', r'\"')
                    
                    csvfile = io.StringIO()
                    writer = csv.writer(csvfile)

                    # Write the headers first
                    headers = _fields
                    
                    writer.writerow(headers)
                    
                    # Now write the data
                    for obj in queryset:
                        row = []
                        for field in _fields:
                            if field is None:
                                continue
                            elif hasattr(obj, field):
                                if field in ('created_on', 'updated_on', 'end_time',):
                                    if getattr(obj, field) is not None:
                                        row.append(timezone.template_localtime(getattr(obj, field)) + timedelta(minutes=offset))
                                    else:
                                        row.append("")
                                else:
                                    row.append(getattr(obj, field))
                            else:
                                # Probably a variable
                                variables = getattr(obj, 'variables')
                                if field in variables:
                                    row.append(variables[field])
                                else:
                                    # This variable doesn't exist. Keep it as empty
                                    row.append("")
                        writer.writerow(row)
                    
                    email.attach(f'{file_name}.csv', csvfile.getvalue(), 'text/csv')
                    num_files += 1
                
                
                if num_files == 0:
                    # No new updates for any bot today
                    default_body = render_to_string('no_new_updates.html', {
                        'user': admin_user,
                    })
                    email.body = default_body
                
                email.send()
            except:
                traceback.print_exc()
                logger.critical(f"Error sending mail to admin {admin_user.email}")

        logger.info("Scheduled mails are sent")
