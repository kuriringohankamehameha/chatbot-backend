from rest_framework.response import Response
from rest_framework import status
import requests
from .models import ScheduleTask
from apps.whatsappbot.models import TemplateApproval
from .serializers import WhatsappMakeScheduleRegDetailSerializer
from apps.whatsappbot.events import send_text_template_message, send_media_template_message
import pandas as pd
import json 
import io
from apscheduler.schedulers.background import BackgroundScheduler
import _thread
from django.utils import timezone, dateformat
from pytz import timezone as pytimezone
from datetime import datetime, timedelta
import chatbot.settings as settings
from celery import task

settings_time_zone = pytimezone(settings.TIME_ZONE)


print("this is time: ", dateformat.format(timezone.now(), 'd/m/Y H:i:s'))
def fetch_csv(request, sched_obj):
    csv_url = request.data['data_url']
    s=requests.get(csv_url).content
    print(s)
    csv=pd.read_csv(io.StringIO(s.decode('utf-8')))
    csv_json = csv.to_json(orient='index')

    request.data['data'] = json.loads(csv_json)

    serializer = WhatsappMakeScheduleRegDetailSerializer(sched_obj, data=request.data, partial=True)
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
#    "data_url": "http://www.sharecsv.com/dl/6b82af13e31a9d8a479786ad83e8b589/temp_csv.csv"
#    "data_url": "http://www.sharecsv.com/dl/7ca449cf88edf7061962b9c80a8e3725/temp_csv.csv"

@task
def whatsapp_template_schedule(pk, api=False):
    print("doing this job ")
    try:
        ## check if scheduled flag is true
        ## option 1
        # if schedule_flag == False:
        #     delete databse
        #     return False

        # datetime.now() != schedule_on
        #     return False

        
        sched_obj = ScheduleTask.objects.get(pk=pk)

        template_hash = sched_obj.template_id.template_hash
        print(template_hash)

        endpoint = sched_obj.wab_client.endpoint
        auth_token = sched_obj.wab_client.authtoken
        namespace = sched_obj.template_id.template_namespace
        elementname = sched_obj.template_id.template_elementname
        policy = sched_obj.template_id.template_policy
        code = sched_obj.template_id.template_code
        param_label = sched_obj.template_id.params
        param_data = sched_obj.data
        extra = sched_obj.template_id.extra

        template_type = sched_obj.template_id.template_type
        
        has_url_button = False
        if extra and "button" in list(extra.keys()) and extra["button_type"] == "call":
            has_url_button = True

        try:
            if template_type == "text":
                final_result = []
                success_rate = {"successful":0, "unsuccessful":0, "invalid-number":0, "success_rate":0}
                for row in param_data:
                    ## reading every row in scheduler data

                    row_dic = row
                    receiver = row_dic['whatsapp_number']
                    del row_dic['whatsapp_number']
                    params=[]
                    print(row_dic, param_label)
                    if len(row_dic.keys())>0:
                        params = [str(row_dic[i]) for i in list(param_label.values())]  #list(row_dic.values())

                    receiver_result = send_text_template_message(receiver, namespace, elementname, policy, code, params, endpoint, auth_token, has_url_button=has_url_button)
                    print("this is result of scheduler", receiver_result)
                    final_result.append(receiver_result[0])

                    success_rate[receiver_result[1]] += 1
                    print("job done")

            elif template_type in ["image", "video", "pdf"]:
                final_result = []
                success_rate = {"successful":0, "unsuccessful":0, "invalid-number":0, "success_rate":0}
                for row in param_data:
                    ## reading every row in scheduler data
                    row_dic = row
                    receiver = row_dic['whatsapp_number']
                    del row_dic['whatsapp_number']
                    params=[]
                    print(row_dic, param_label)
                    link = ""
                    if "link" in list(row_dic.keys()):
                        link = row_dic["link"]
                    if len(row_dic.keys())>1:
                        params = [str(row_dic[i]) for i in list(param_label.values())]  #list(row_dic.values())

                    receiver_result = send_media_template_message(receiver, namespace, elementname, policy, code, params, endpoint, auth_token, template_type, link, has_url_button=has_url_button)
                    print("this is result of scheduler", receiver_result)
                    final_result.append(receiver_result[0])

                    success_rate[receiver_result[1]] += 1
                    print("job done")

            success_rate["success_rate"] = format((int(success_rate["successful"])*100)/len(param_data), ".2f")
            
            if not api:
                instance = ScheduleTask.objects.filter(pk=pk).update(scheduled_flag = True, task_done = True, scheduler_result=final_result, schedulers_success_rate=success_rate)
            else:
                instance = ScheduleTask.objects.filter(pk=pk).update(scheduled_flag = False, task_done = False, scheduler_result=final_result, schedulers_success_rate=success_rate)
            ## update msg count of template
            tot_count = TemplateApproval.objects.get(pk=template_hash).msg_count
            record_outgoing = int(tot_count['outgoing']) + len(param_data)
            TemplateApproval.objects.filter(pk=template_hash).update(msg_count={"outgoing":record_outgoing})

            return True


        except Exception as ex:
            print("error in askscheduler>events: ", ex)
            return False
            
    except Exception as ex:
            print("error in askscheduler>events: ", ex)
            return False

def temp_job():
    print("hello world")

class WhatsappScheduler:
    print("----- Setting up scheduler -------------")
    sched = BackgroundScheduler({'apscheduler.timezone': 'UTC'})
    sched.start()


    # database = [id1, id2, id3]
    def __init__(self):
        try:
            self.already_scheduled_jobs = ScheduleTask.objects.filter(scheduled_flag=True, task_done=False).values()
            for job in self.already_scheduled_jobs:
                sched_hash= job['sched_hash']
                sched_tz = job['scheduler_tz']
                print(sched_hash, sched_tz)
                WhatsappScheduler.setup_whatsapp_template_schedule(sched_hash, sched_tz)
        except Exception as ex:
            print("error in scheduler init --> ", ex)

    @staticmethod
    def setup_whatsapp_template_schedule(pk, sched_tz):
        try:
            print
            sched_obj = ScheduleTask.objects.get(pk=pk)
            scheduled_on = sched_obj.scheduled_on
            settings_sched_time_zone = pytimezone(sched_tz)
            print("before changing, ",scheduled_on)

            local_now = datetime.now(pytimezone(sched_tz))
            offset = local_now.utcoffset().total_seconds()
            print(offset)

            offset_delta = timedelta(seconds=offset)
            
            # scheduled_on = scheduled_on.astimezone(settings_time_zone).replace(tzinfo=settings_sched_time_zone)
            scheduled_on = scheduled_on - offset_delta

            print("scheduling job ", str(scheduled_on))
            print(pk)
            WhatsappScheduler.sched.add_job(whatsapp_template_schedule, 'date', run_date=str(scheduled_on), args=[pk], id=str(pk))
            
            sched_obj.scheduled_flag = True
            sched_obj.task_done = False
            sched_obj.save()
            return Response({"scheduled_flag":True, "task_done":False}, status=status.HTTP_201_CREATED)
        except Exception as ex:
            print(ex)
            return Response(status=status.HTTP_400_BAD_REQUEST)
    
    @staticmethod
    def get_task_info(id="", all=True):
        try:
            jobs = WhatsappScheduler.sched.get_jobs()
            print("these are all jobs --> ", jobs)
            all_tasks = []
            for job in jobs:
                all_tasks.append(job.id)
            print(all_tasks)
            return Response(all_tasks, status=status.HTTP_200_OK)
            # print("this is specific job with given id: ", WhatsappScheduler.sched.get_job(id))
            # return Response(status=status.HTTP_200_OK)
        except Exception as ex:
            print(ex)
            return Response(status=status.HTTP_400_BAD_REQUEST)
    
    @staticmethod
    def delete_given_job(id):
        try:
            WhatsappScheduler.sched.remove_job(id)

            sched_obj = ScheduleTask.objects.get(pk=id)
            sched_obj.scheduled_flag = False
            sched_obj.task_done = False
            sched_obj.save()
            return Response({"scheduled_flag":False, "task_done":False}, status=status.HTTP_200_OK)
        except Exception as ex:
            print(ex)
            return Response(status=status.HTTP_400_BAD_REQUEST)
## {"scheduled_on":"2020-09-06T04:05:04"}