import copy
import json
import os
import re
import uuid

from decouple import config
from django.contrib.sites.shortcuts import get_current_site
from django.core.mail import EmailMessage
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import generics, parsers, permissions, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .apps import REDIS_CONNECTION
from .models import (BotBuilderImage, Chatbox, ChatboxAppearance,
                     ChatboxDetail, ChatboxMobileAppearance, ChatboxPage,
                     ChatboxUrls, ChatRoom, TemplateChatbox)
from .parse_json import parse_json
from .serializers import (BotBuilderImageSerializer, ChatboxDetailSerializer,
                          ChatboxListSerializer,
                          ChatboxMobileAppearanceSerializer,
                          ChatboxPageSerializer, ChatboxPublishSerializer,
                          ChatboxRegDetailSerializer, ChatboxUrlSerializer,
                          ChatRoomSerializer, ClassAppearanceUpdateSerializer,
                          CreateChatboxTemplateSerializer,
                          DuplicateChatbotSerializer,
                          FrontendChatbotTemplateApiSerializer,
                          SendEmailSerializer)
from .template import jsString


class SendEmail(generics.GenericAPIView):
    serializer_class = SendEmailSerializer
    def post(self, request, *args, **kwargs):
        serializer = SendEmailSerializer(data=request.data)
        if serializer.is_valid():
            from_email = serializer.data['from_email']
            to_email = serializer.data['to_email']
            subject = serializer.data['subject']
            content = serializer.data['content']

            email = EmailMessage(subject, content, from_email=[from_email], to=[to_email])
            email.send()

            return Response('Email Sent', status=status.HTTP_200_OK)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)




class ChatboxList(APIView):

    permission_classes = [IsAuthenticated]

    def get(self, request, format=None):
        queryset = Chatbox.objects.filter(owner=self.request.user, is_deleted=False)
        serializer = ChatboxListSerializer(queryset, many=True)
        return Response(serializer.data)

    def put(self, request):
        queryset = Chatbox.objects.filter(owner=self.request.user, is_deleted=False).order_by('-created_on')
        total_length = queryset.count()
        total_page = int(total_length/10)
        if total_page < (total_length/10):
            total_page =+ 1
        if 'page' in request.data:
            page = request.data['page']
            gap = 10
            queryset = queryset[gap*int(page)-gap:gap*int(page)]
        current_length = queryset.count()
        serializer = ChatboxListSerializer(queryset, many=True)        
        return Response({'total_length': total_length, 'current_length': current_length,
            'data':serializer.data, 'total_page': total_page})    

    def post(self, request, format=None):
        serializer = ChatboxListSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(owner=self.request.user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# According to Payment Display        
class ChatboxListAPI(APIView):

    permission_classes = [IsAuthenticated]

    def get(self, request, format=None):
        if self.request.user.paid:
            queryset = Chatbox.objects.filter(owner=self.request.user, is_deleted=False)
            serializer = ChatboxListSerializer(queryset, many=True)
            return Response(serializer.data)
        else:
            return Response(status=status.HTTP_402_PAYMENT_REQUIRED)    

    def post(self, request, format=None):
        serializer = ChatboxListSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(owner=self.request.user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ChatboxDetailAPI(APIView):

    permission_classes = [IsAuthenticated]

    def get_object(self, pk):
        try:
            return Chatbox.objects.get(pk=pk)
        except Chatbox.DoesNotExist:
            raise Http404

    def get(self, request, pk, format=None):
        chatbot_obj = self.get_object(pk)
            
        serializer = ChatboxRegDetailSerializer(chatbot_obj)
        return Response(serializer.data)

    def put(self, request, pk, format=None):
        chatbot_obj = self.get_object(pk)


        if 'bot_full_json' in request.data:
            bot_full_json = copy.deepcopy(request.data['bot_full_json'])
            request.data['bot_data_json'], request.data['bot_variable_json'], request.data['bot_lead_json'], options = parse_json(
                bot_full_json
                )
            if options != {}:
                if 'subscribe_email' in options and options['subscribe_email'] == True:
                    request.data['subscription_type'] = 'email'
        
        if 'bot_data_json' in request.data and 'bot_variable_json' in request.data and 'bot_lead_json' in request.data:
            if request.data['bot_data_json'] == {} and request.data['bot_variable_json'] == {} and request.data['bot_lead_json'] == {}:
                return Response('Error in bot config', status=status.HTTP_400_BAD_REQUEST)
        
        if 'bot_variable_json' in request.data:
            # Union it with the variable_columns
            variable_columns = chatbot_obj.variable_columns
            if variable_columns is None:
                variable_columns = list()
            request.data['variable_columns'] = list(set().union(*[request.data['bot_variable_json'], variable_columns]))
        
        if 'bot_lead_json' in request.data:
            # Now every lead variable must belong to bot_variable_json
            # If not, we must remove it
            if 'bot_variable_json' not in request.data:
                # Bad request
                return Response("bot_variable_json must be provided with bot_lead_json", status=status.HTTP_400_BAD_REQUEST)
            
            lead_fields = list(request.data['bot_lead_json'].keys())
            lead_fields = [lead_field for lead_field in lead_fields if lead_field in request.data['bot_variable_json']]
            request.data['bot_lead_json'] = {lead_field: "" for lead_field in lead_fields}

            if request.data['bot_lead_json'] in (None, {}):
                # If this is empty, we'll have the fallback option use @email and @phone as the lead fields
                request.data['bot_lead_json'] = {'@email': '', '@phone': ''}
        
        serializer = ChatboxRegDetailSerializer(chatbot_obj, data=request.data, partial=True)

        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        print(serializer.errors)    
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk, format=None):
        chatbot_obj = self.get_object(pk)
        chatbot_obj.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ChatboxAppearanceUpdateView(APIView):

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        pk = self.kwargs.get('pk')
        chatbox = get_object_or_404(Chatbox, pk=pk)
        chatbotapp = get_object_or_404(ChatboxAppearance, chatbox__pk=pk)
        serial = ClassAppearanceUpdateSerializer(instance=chatbotapp, context={'chatboxname': chatbox.title})
        return Response(serial.data)

    def put(self, request, pk, format=None):
        pk = self.kwargs.get('pk')
        chatbotapp = get_object_or_404(ChatboxAppearance, chatbox__pk=pk)
        chatboxname = ''
        if 'chatboxname' in request.data.keys():
            chatboxname = request.data['chatboxname']
        print(chatboxname)
        serial = ClassAppearanceUpdateSerializer(instance=chatbotapp, data=request.data, partial=True,
                                                 context={'chatboxname': chatboxname,
                                                          'chatbox_pk': pk})
        if serial.is_valid():
            serial.save()
            return Response(serial.data)
        return Response(serial.errors)



class ChatboxMobileAppearanceUpdateView(generics.RetrieveUpdateAPIView):
    serializer_class = ChatboxMobileAppearanceSerializer
    permission_classes = [permissions.IsAuthenticated,]
    def get_queryset(self):
        pk = self.kwargs.get('pk')
        return ChatboxMobileAppearance.objects.filter(chatbox__bot_hash=pk)



class ChatboxDetailUpdateView(generics.RetrieveUpdateAPIView):
    serializer_class = ChatboxDetailSerializer
    permission_classes = [permissions.IsAuthenticated,]
    def get_queryset(self):
        pk = self.kwargs.get('pk')
        return ChatboxDetail.objects.filter(chatbox__bot_hash=pk)


class ChatboxPageUpdateView(generics.RetrieveUpdateAPIView):
    serializer_class = ChatboxPageSerializer
    permission_classes = [permissions.IsAuthenticated,]
    def get_queryset(self):
        pk = self.kwargs.get('pk')
        return ChatboxPage.objects.filter(chatbox__bot_hash=pk)


class ChatboxUrlList(APIView):

    permission_classes = [IsAuthenticated]

    def get_object(self, bot_hash):
        try:
            return Chatbox.objects.get(pk=bot_hash)
        except Chatbox.DoesNotExist:
            raise Http404
    

    def get(self, request, bot_hash):

        query_params = request.query_params

        chatbox = self.get_object(bot_hash)

        _status = "all"

        if 'status' in query_params:
            if query_params['status'] not in ('all', 'published', 'unpublished',):
                return Response(f"'status' query parameter must be one of ('all', 'published', 'unpublished')", status=status.HTTP_400_BAD_REQUEST)
            
            _status = query_params['status']
        
        if _status == 'all':
            # No filter
            queryset = ChatboxUrls.objects.filter(bot_hash=chatbox)
        else:
            if _status == 'published':
                queryset = ChatboxUrls.objects.filter(bot_hash=chatbox, publish_status=True)
            else:
                queryset = ChatboxUrls.objects.filter(bot_hash=chatbox, publish_status=False)

        serializer = ChatboxUrlSerializer(queryset, many=True)

        return Response(serializer.data, status=status.HTTP_200_OK)


class PublishChatbox(APIView):

    permission_classes = [IsAuthenticated]

    def get_object(self, pk):
        try:
            return Chatbox.objects.get(pk=pk)
        except Chatbox.DoesNotExist:
            raise Http404
                        
    def put(self, request, pk):

        chatbox = self.get_object(pk)
        server_url = str(config('SERVER_URL'))

        if 'website_url' not in request.data:
            return Response("website_url field is not present", status=status.HTTP_400_BAD_REQUEST)
        
        url = request.data['website_url']

        # TODO: Check for the file path sanity. url ends with `.com`
        request.data['js_file_path'] = f'https://{server_url}/widget/chatbox/bot_js/{pk}_{url}.js'
        
        request.data["bot_hash"] = chatbox

        serializer = ChatboxPublishSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        
        try:
            if chatbox.publish_status is False:
                file_text = jsString.format(server_url, str(pk), str(url))
                file_path = os.path.join('widget', 'chatbox/bot_js', f'{pk}_{url}.js')
                with open(file_path, 'w+') as file_obj:
                    file_obj.write(file_text)
                chatbox.publish(url, serializer.data['js_file_path'])
            else:
                chatbox.publish(url, serializer.data['js_file_path'])
        
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Exception as ex:
            print(ex)
            return Response(f"Error during generating template file", status=status.HTTP_400_BAD_REQUEST)


class BotBuilderImageAPI(APIView):    
    parser_classes = [parsers.MultiPartParser, parsers.FormParser, parsers.JSONParser]
    serializer_class = BotBuilderImageSerializer
    def post(self, request, pk):
        images = dict(request.data)['image']
        img_list = []
        current_site = get_current_site(request)
        print(images)
        chatbox_instance = get_object_or_404(Chatbox, bot_hash=pk)
        for img in images:
            try:
                bot_image = BotBuilderImage(chatbox=chatbox_instance, image=img)
                bot_image.save()
                img_list.append("https://" + current_site.domain + bot_image.image.url)
            except Exception as e:
                print(e)
                return Response(status=status.HTTP_400_BAD_REQUEST)        
        return Response(img_list)




class DuplicateChatbot(generics.GenericAPIView):
    '''
    Api for creating duplicate of chatbot.
    Just need bot_hash in the post request.

    Endpoint: chatbox/duplicate
    '''
    serializer_class = DuplicateChatbotSerializer
    permission_classes = [IsAuthenticated]
    def post(self, request, *args, **kwargs):
        try:
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            bot_hash = serializer.data['bot_hash']
            chatbox = get_object_or_404(Chatbox, bot_hash=bot_hash)
            chatbox.pk = None
            chatbox.title = '(Copy)' + str(chatbox.title)
            chatbox.publish_status = False
            chatbox.save()        
            return Response(ChatboxListSerializer(chatbox).data)
        except Exception as e:
            return Response({'status': 'Something Went Wrong'}, status=status.HTTP_400_BAD_REQUEST)



class DeleteChatbot(APIView):
    '''
    Api for deleting the chatbot.
    Not permanantly deleting but marking is_deleted=True
    Endpoint: chatbox/delete/<uuid:pk>
    '''
    permission_classes = [IsAuthenticated]
    def get(self, request, *args, **kwargs):
        bot_hash = self.kwargs.get('pk')
        chatbox = get_object_or_404(Chatbox, bot_hash=bot_hash)
        if chatbox.is_deleted:
            return Response({"status": "Already Deleted"}, status=status.HTTP_404_NOT_FOUND)
        else:
            return Response(ChatboxListSerializer(chatbox).data, status=status.HTTP_200_OK)    

    def delete(self, request, *args, **kwargs):
        try:
            bot_hash = self.kwargs.get('pk')
            Chatbox.objects.filter(bot_hash=bot_hash).update(is_deleted=True)
            file_location = '/av_projects/chatbot/backend/widget/chatbox/bot_js/{}.js'.format(str(bot_hash))
            if os.path.exists(file_location):
                os.remove(file_location)       
            return Response({'status':'Deleted'}, status=status.HTTP_200_OK)    
        except Exception as e:
            print(e)
            return Response({'status': 'Something went wrong.'}, status=status.HTTP_400_BAD_REQUEST) 


# Chatbot TemplateApi
class CreateChatboxTemplate(generics.GenericAPIView):
    serializer_class = CreateChatboxTemplateSerializer
    permission_classes = [IsAuthenticated, ]

    def get_queryset(self):
        return TemplateChatbox.objects.filter(is_deleted=False)

    def get(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_queryset(), many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)    


class UpdateChatboxTemplate(generics.RetrieveUpdateAPIView):

    serializer_class = CreateChatboxTemplateSerializer
    permission_classes = [IsAuthenticated, ]

    def get_queryset(self):
        pk = self.kwargs.get('pk')
        return TemplateChatbox.objects.filter(bot_hash=pk, is_deleted=False)


class FrontendChatbotTemplateApi(generics.GenericAPIView):
    serializer_class = FrontendChatbotTemplateApiSerializer
    permission_classes = [IsAuthenticated, ]

    def get_queryset(self):
        return TemplateChatbox.objects.filter(is_deleted=False)

    def get(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = CreateChatboxTemplateSerializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request, *args, **kwargs):
        try:
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            template_bot_hash = serializer.data['template_bot_hash']
            template_bot = TemplateChatbox.objects.get(bot_hash=template_bot_hash, is_deleted=False)
            chatbot = Chatbox()
            chatbot.title = template_bot.title
            chatbot.bot_data_json = template_bot.bot_data_json
            chatbot.bot_full_json = template_bot.bot_full_json
            chatbot.bot_variable_json = template_bot.bot_variable_json
            chatbot.chatbot_type = template_bot.chatbot_type
            chatbot.bot_lead_json = template_bot.bot_lead_json
            chatbot.variable_columns = template_bot.variable_columns
            chatbot.subscription_type = template_bot.subscription_type
            chatbot.owner = request.user
            chatbot.save()
            return Response(ChatboxListSerializer(chatbot).data, status=status.HTTP_201_CREATED)
        except Exception as e:
            print(e)
            return Response({'status': 'Something Went Wrong'}, status=status.HTTP_404_NOT_FOUND)


def botjs_handler(request):
    bot_hash = request.headers['Bothash'].split('.')[0]
    try:
        chatbox = Chatbox.objects.get(bot_hash=bot_hash)
    except Chatbox.DoesNotExist:
        raise Http404

    owner_website = request.headers['Referer']
    owner_website = re.sub(r'(.*://)?([^/?]+).*', '\g<1>\g<2>', owner_website)
    if chatbox.website_url == owner_website:
        return HttpResponse(status=200)
    return HttpResponse(status=400)



class ChatboxUrls(models.Model):
    # Model which maps a single website bot to multiple hosted URLs
    bot_hash = models.ForeignKey('Chatbox', related_name="chatbox_urls", db_column="bot_hash", on_delete=models.CASCADE)
    website_url = models.URLField(max_length=255, blank=True, db_column="website_url")
    js_file_path = models.URLField(max_length=255, blank=True, db_column="js_file_path", default="")
    publish_status = models.BooleanField(default=False, db_column="publish_status")



     path('chatbox/<uuid:bot_hash>/urls', api.ChatboxUrlList.as_view()),
