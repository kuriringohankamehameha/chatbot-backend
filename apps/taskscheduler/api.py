from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.http import Http404
from .models import ScheduleTask
from apps.whatsappbot.models import WhatsappClients, TemplateApproval
from .serializers import WhatsappMakeScheduleListSerializer, WhatsappMakeScheduleRegDetailSerializer
from rest_framework.permissions import IsAuthenticated
from decouple import config
from django.utils import timezone
from .events import fetch_csv, whatsapp_template_schedule, WhatsappScheduler
import _thread
import requests
import pandas as pd
import io
import json
from django.utils.dateparse import parse_datetime
import datetime 
import chatbot.settings as settings
from pytz import timezone as pytimezone
import pytz


settings_sched_time_zone = pytimezone(settings.SCHED_TIME_ZONE)
settings_time_zone = pytimezone(settings.TIME_ZONE)

class WhatsappMakeSchedule(APIView):
    ''' Api for getting all existing scheduled jobs and 
    making new scheduled jobs '''

    permission_classes = [IsAuthenticated]

    def get(self, request, admin=0, format=None):
        
        if admin==1:
            if request.user.role == "SA" and not request.user.user_is_deleted:
                queryset = ScheduleTask.objects.all().order_by('-created_on')
                serializer = WhatsappMakeScheduleListSerializer(queryset, many=True)
            else:
                return Response(status=status.HTTP_401_UNAUTHORIZED)
        else:
            queryset = ScheduleTask.objects.filter(owner=self.request.user).order_by('-created_on')
            serializer = WhatsappMakeScheduleListSerializer(queryset, many=True)
        return Response(serializer.data)
       

    def post(self, request, admin=0, format=None):
        request.data["template_title"] = TemplateApproval.objects.get(pk=request.data["template_id"]).title
        request.data["wab_title"] = WhatsappClients.objects.get(pk=request.data["wab_client"]).title
        request.data["template_type"] = TemplateApproval.objects.get(pk=request.data["template_id"]).template_type
        request.data["extra"] = {"data_len": 0}
        
        serializer = WhatsappMakeScheduleListSerializer(data=request.data)
        if serializer.is_valid(raise_exception=True):
            serializer.save(owner=self.request.user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class WhatsappMakeScheduleDetailAPI(APIView):
    ''' Api  to update or delete existing business channel'''

    def get_object(self, pk):
        try:
            return ScheduleTask.objects.get(pk=pk)
        except ScheduleTask.DoesNotExist:
            raise Http404

    def get(self, request, pk, format=None):
        sched_obj = self.get_object(pk)
        serializer = WhatsappMakeScheduleRegDetailSerializer(sched_obj)
        data = serializer.data
        
        return Response(data)
        

    def put(self, request, pk, format=None):
        sched_obj = self.get_object(pk)
        ## _thread.start_new_thread(fetch_csv, (request, sched_obj))
        try:
            if 'scheduler_excel' in list(request.data.keys()):
                file = request.data['scheduler_excel']
                
                if "csv" in str(file.name):
                    print("csv inside")
                    csv=pd.read_csv(file, dtype=str)
                elif "xlsx" in str(file.name):
                    print("xlsx inside", file.name)
                    csv = pd.read_excel(file, dtype=str)
                else:
                    print("unsupported")
                    return Response(status=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE)
                
                csv.dropna(subset=["whatsapp_number"], inplace=True)
                print(csv)
                csv_json = csv.to_json(orient='index')

                request.data['data'] = list(json.loads(csv_json).values())  ## [{wa:"", p1:"", p2:"", link:""}, {wa:"", p1:"", p2:"", link:""}]

                param_labels = request.data['data'][0] ## {wa:"", p1:"", p2:"", link:""}
                param_labels = list(param_labels.keys())
                print(param_labels)

                ## check if parameters match
                if "whatsapp_number" not in param_labels:
                    return Response("missing 'whatsapp_number' param ", status=status.HTTP_409_CONFLICT)
                if sched_obj.template_id.template_type !="text":
                    if "link" not in param_labels:
                        return Response("missing 'link' param ", status=status.HTTP_409_CONFLICT)
                    param_labels.remove("link")

                if set(param_labels) & set(list(sched_obj.template_id.params.values())) != set(list(sched_obj.template_id.params.values())):
                    return Response("param's labels mismatch", status=status.HTTP_409_CONFLICT)
                
                if len(param_labels) - 1 != len(list(sched_obj.template_id.params.keys())):
                    return Response("param's length mismatch", status=status.HTTP_409_CONFLICT)

                if sched_obj.template_id.template_type !="text":
                    param_labels.append("link")
                

                # if all correct
                request.data['param_label'] = param_labels

                request.data["extra"] = {"data_len": len(request.data['data'])}

    
            if 'scheduled_on' in list(request.data.keys()):
                print(request.data['scheduled_on'])
                print(request.data["scheduler_tz"])

                settings_sched_time_zone = pytimezone(request.data["scheduler_tz"])
                
                request.data['scheduled_on'] = parse_datetime(request.data['scheduled_on'])
                print(request.data['scheduled_on'].replace(tzinfo=datetime.timezone.utc), "  //////  " , timezone.now().astimezone(settings_sched_time_zone).replace(tzinfo=settings_time_zone))
                
                if request.data['scheduled_on'].replace(tzinfo=datetime.timezone.utc) < timezone.now().astimezone(settings_sched_time_zone).replace(tzinfo=settings_time_zone):
                    return Response("scheduled time already passed.", status=status.HTTP_409_CONFLICT)
                

            serializer = WhatsappMakeScheduleRegDetailSerializer(sched_obj, data=request.data, partial=True)
            if serializer.is_valid(raise_exception=True):
                serializer.save()
                return Response(serializer.data)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        except Exception as ex:
            print(ex)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk, format=None):
        try:
            chatbot_obj = self.get_object(pk)
            chatbot_obj.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        except TemplateApproval.DoesNotExist:
            raise Http404


class WhatsappSendTemplateMessage(APIView):
    ''' Api to send template messages'''

    def get_object(self, pk):
        try:
            return ScheduleTask.objects.get(pk=pk)
        except ScheduleTask.DoesNotExist:
            raise Http404
    

    def post(self, request, pk, now=0):
        sched_obj = self.get_object(pk)
        data_labels_len = len(sched_obj.param_label) - 1
        template_labels_len = len(list(sched_obj.template_id.params.keys()))
        print(now, data_labels_len, template_labels_len)

        try:
            print(now, type(now))
            if not now:
                settings_sched_time_zone = pytimezone(request.data["scheduler_tz"])
                if sched_obj.scheduled_on.replace(tzinfo=datetime.timezone.utc) < timezone.now().astimezone(settings_sched_time_zone).replace(tzinfo=settings_time_zone):
                    return Response("Date and time incorrect", status=status.HTTP_400_BAD_REQUEST)
                ## put data in database and then schedule the job for it
                return WhatsappScheduler.setup_whatsapp_template_schedule(pk, request.data["scheduler_tz"])

            else:
                ## send now
                res = whatsapp_template_schedule.delay(pk, api=True)
                if res:
                    return Response(status=status.HTTP_200_OK)
                return Response(status=status.HTTP_400_BAD_REQUEST)
        except Exception as ex:
            print(ex)
            return Response(status=status.HTTP_400_BAD_REQUEST)

class RunningSchedulerDetails(APIView):
    ## scheduling all previous jobs
    WhatsappScheduler()

    def get(self,request,pk, delete=0, admin=0):
        if admin:
            return WhatsappScheduler.get_task_info()
        return Response(status=status.HTTP_423_LOCKED)

    def post(self, request, pk, delete=0, admin=0):
        if delete:
            return WhatsappScheduler.delete_given_job(str(pk))