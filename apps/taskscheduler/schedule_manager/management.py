from apscheduler.schedulers.background import BackgroundScheduler 
from decouple import config

from apps.taskscheduler.schedule_manager.jobs import ClientWidgetJobs
from apps.clientwidget.views import lock_timeout

if lock_timeout // 3600 <= 0:
    session_timeout = 6 # 6 hours
else:
    session_timeout = lock_timeout // 3600

scheduler = BackgroundScheduler()

try:
    DEVELOPMENT = config('DEVELOPMENT', cast=bool)
except:
    DEVELOPMENT = False

def start():
    # ------------------------- #
    # Clientwidget related jobs #
    # scheduler.add_job(ClientWidgetJobs.clientwidget_session_update, 'cron', hour="8") # 8AM Job
    scheduler.add_job(ClientWidgetJobs.clientwidget_send_email, 'cron', hour="8", minute="30") # 8:30 AM Job
    scheduler.add_job(ClientWidgetJobs.clientwidget_session_update, 'cron', hour=f"*/{session_timeout}") # Every session_timeout hours

    if DEVELOPMENT == True:
        scheduler.add_job(ClientWidgetJobs.send_dummy_email, 'cron', hour="*") # Every hour
    # ------------------------- #

    scheduler.start()

