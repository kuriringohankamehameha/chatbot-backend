import binascii
import copy
import json
import os
import re
import traceback
import uuid

from decouple import config
from django.contrib.sites.shortcuts import get_current_site
from django.core.cache import cache
from django.core.mail import EmailMessage
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import generics, parsers, permissions, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.clientwidget.models import ClientMediaHandler
from apps.clientwidget.models import AdminMediaHandler
from apps.clientwidget.models import ChatRoom as ClientwidgetChatroom
from .chatbox_templates import ChatboxAppearanceTemplate

from .apps import REDIS_CONNECTION
from .bot_json_parser import BotJSONParseError, BotJSONParser
from .models import (BotBuilderImage, Chatbox, ChatboxAppearance,
                     ChatboxDetail, ChatboxMobileAppearance, ChatboxPage,
                     ChatboxUrls, ChatRoom, TemplateChatbox)
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
from datetime import date, datetime, timedelta


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
        queryset = Chatbox.objects.filter(owner=self.request.user, is_deleted=False).order_by('-created_on')
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

    def get_object(self, pk, owner_id=None):
        try:
            if self.request.user.role in ['SA']:
                return Chatbox.objects.get(pk=pk)
            return Chatbox.objects.get(pk=pk, owner_id=owner_id)
        except Chatbox.DoesNotExist:
            raise Http404

    def get(self, request, pk, format=None):

        if request.user.role in ['SA']:
            chatbot_obj = self.get_object(pk)
        else:
            chatbot_obj = self.get_object(pk, owner_id=request.user.pk)
            
        serializer = ChatboxRegDetailSerializer(chatbot_obj)
        return Response(serializer.data)

    def put(self, request, pk, format=None):
        chatbot_obj = self.get_object(pk, owner_id=request.user.pk)

        if 'bot_full_json' in request.data:
            bot_full_json = copy.deepcopy(request.data['bot_full_json'])
            
            if 'restricted_variables' in request.data:
                restricted_variables = request.data['restricted_variables']
            else:
                restricted_variables = None
            
            try:
                try:
                    DEVELOPMENT = config('DEVELOPMENT', cast=bool)
                except:
                    DEVELOPMENT = False
                
                parser = BotJSONParser(restricted_variables=restricted_variables)
                request.data['bot_data_json'], request.data['bot_variable_json'], request.data['bot_lead_json'], options = parser.parse_json(
                    bot_full_json
                    )
                
                #if DEVELOPMENT == True:
                #    parser.semantic_analysis()

            except BotJSONParseError as ex:
                error_msg = str(ex)
                traceback.print_exc()
                return Response(f'{error_msg}', status=status.HTTP_400_BAD_REQUEST)

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

            #if request.data['bot_lead_json'] in (None, {}):
                # If this is empty, we'll have the fallback option use @email and @phone as the lead fields
                #request.data['bot_lead_json'] = {'@email': '', '@phone': ''}
        
        serializer = ChatboxRegDetailSerializer(chatbot_obj, data=request.data, partial=True)

        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        print(serializer.errors)    
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)



class ChatboxAppearanceUpdateView(APIView):
    def validate_preview(self, request, param='preview'):
        result = False
        if param in request.query_params and request.query_params[param] == "true":
            server_url = config('SERVER_URL')
            try:
                sub_domain = str(config('SUB_SERVER_URL'))
                if sub_domain is not '':
                    subdomain_server_url = sub_domain + "." + server_url
                else:
                    subdomain_server_url = server_url
            except Exception as e:
                print(e)
                subdomain_server_url = server_url
            if request.query_params['website_url'].startswith((f"{server_url}", f"{subdomain_server_url}",)):
                result = True
            else:
                result = False
        else:
            result = False
        return result
    
    def get_bot_obj_or_404(self, pk):
        chatbox_obj = get_object_or_404(Chatbox, pk=pk)
        if chatbox_obj.is_deleted:
            raise Http404("Oops. The page you're looking for is not found!")
        return chatbox_obj

    def get(self, request, pk):
        pk = self.kwargs.get('pk')

        # Change this. Currently, any user can simulate a preview request by manipulating website_url and preview parameters
        if not request.user.is_authenticated:
            for _ in range(1):
                if 'website_url' not in request.query_params:
                    return Response("URL not found", status=status.HTTP_404_NOT_FOUND)

                preview = self.validate_preview(request, param='preview')
                standalone = self.validate_preview(request, param='standalone')
                
                try:
                    if 'website_url' in request.query_params:
                        owner_website = request.query_params['website_url']
                        if owner_website[-1] == '/':
                            owner_website = owner_website[:-1]
                        
                        if owner_website is not None:
                            owner_website = owner_website.split('?', 1)[0]
                    try:
                        value = cache.get(f"CLIENTWIDGET_TEMPLATE_{owner_website}")
                        if value == False:
                            return Response("Bot is currently not published", status=status.HTTP_404_NOT_FOUND)
                        
                        if (value is not None) and (str(value) == str(pk)):
                            break
                    except Exception as ex:
                        print(ex)
                    
                    # Really shitty code
                    if preview == False and standalone == False:
                        # Check for publish_status
                        chatbox = self.get_bot_obj_or_404(pk)
                        chatbotapp = get_object_or_404(ChatboxAppearance, chatbox__pk=pk)
                        instance = ChatboxUrls.objects.filter(bot_hash=chatbox, website_url=owner_website).first()
                        if instance is None:
                            # Now check for subdomain match
                            queryset = ChatboxUrls.objects.filter(bot_hash=chatbox, allow_subdomain=True, publish_status=True)
                            for obj in queryset:
                                if obj.website_url is None:
                                    continue

                                _url = obj.website_url
                                if _url[-1] == '/':
                                    _url = _url[:-1]

                                if owner_website.startswith(_url + "/"):
                                    cache.set(f"CLIENTWIDGET_TEMPLATE_{_url}", str(pk), timeout=24 * 60 * 60)
                                    instance = obj
                                    break
                            
                            if instance is None:
                                return Response("URL not found", status=status.HTTP_404_NOT_FOUND)
                            else:
                                break
                        else:
                            if instance.publish_status == True:
                                cache.set(f"CLIENTWIDGET_TEMPLATE_{owner_website}", str(pk), timeout=24 * 60 * 60)
                            else:
                                cache.set(f"CLIENTWIDGET_TEMPLATE_{owner_website}", False, timeout=24 * 60 * 60)
                        if instance.publish_status == False:
                            return Response("Bot is currently not published", status=status.HTTP_404_NOT_FOUND)
                except Exception as ex:
                    print(ex)
                    return Response("Something really bad happened", status=status.HTTP_400_BAD_REQUEST)
        if (request.user.is_authenticated) or (preview == True or standalone == True) or (not request.user.is_authenticated and (preview == False and standalone == False)):
            chatbox = self.get_bot_obj_or_404(pk)
            chatbotapp = get_object_or_404(ChatboxAppearance, chatbox__pk=pk)
        
        serial = ClassAppearanceUpdateSerializer(instance=chatbotapp, context={'chatboxname': chatbox.title})
        
        subscription_type = chatbox.subscription_type
        cron = True if subscription_type in ('cron',) else False

        chatbox_toggles = {
            'chatbox_toggles': {
                'cron': cron
            }
        }

        data = serial.data

        for key in ['chatboxname', 'json_info']:
            if data.get(key) in (None, {},):
                data[key] = ChatboxAppearanceTemplate.get(key)

        response = Response({**(data), **chatbox_toggles})
        response['Access-Control-Allow-Origin'] = '*'
        return response

    def put(self, request, pk, format=None):
        if not request.user.is_authenticated:
            return Response("Anonymous User is not allowed", status=status.HTTP_403_FORBIDDEN)
        
        pk = self.kwargs.get('pk')
        chatbotapp = get_object_or_404(ChatboxAppearance, chatbox__pk=pk, chatbox__owner_id=request.user.pk)
        chatboxname = ''
        if 'chatboxname' in request.data.keys():
            chatboxname = request.data['chatboxname']
        
        if 'json_info' not in request.data:
            return Response("Need to send json_info", status=status.HTTP_400_BAD_REQUEST)
        
        # All Chatbox toggles comes here
        if 'chatbox_toggles' in request.data['json_info']:
            try:
                chatbox_toggles = json.loads(request.data['json_info'])['chatbox_toggles']
                if 'cron' in chatbox_toggles:
                    if chatbox_toggles['cron'] == True:
                        target = 'cron'
                    else:
                        target = ''
                    
                    chatbox = self.get_bot_obj_or_404(pk)
                    
                    subscription_type = chatbox.subscription_type
                    
                    modified = False

                    if subscription_type != target:
                        modified = True
                    
                    if modified == True:
                        chatbox.subscription_type = target
                        chatbox.save()
            finally:
                pass

        serial = ClassAppearanceUpdateSerializer(instance=chatbotapp, data=request.data, partial=True,
                                                 context={'chatboxname': chatboxname,
                                                          'chatbox_pk': pk})
        if serial.is_valid():
            serial.save()
            return Response(serial.data)
        return Response(serial.errors)


class ChatboxCustomizationView(APIView):
    permission_classes = [IsAuthenticated]

    template_customizations = {
        'cron': False,
    }

    def get(self, request, pk, format=None):
        chatbox = get_object_or_404(Chatbox, pk=pk, owner_id=request.user.pk)
        data = {'customizations': {**(self.template_customizations), **(chatbox.customizations)}}
        
        return Response(data, status=status.HTTP_200_OK)

    def put(self, request, pk):
        # All Chatbox toggles comes here
        if 'customizations' not in request.data or (not isinstance(request.data['customizations'], dict)):
            return Response(f"Need to send 'customizations' Object", status=status.HTTP_400_BAD_REQUEST)
        
        try:
            customizations = request.data['customizations']

            required_fields = ["cron"]

            chatbox = get_object_or_404(Chatbox, pk=pk)

            for field in required_fields:
                if customizations.get(field) is None:
                    return Response(f"Required Customization field: {field} is not sent", status=status.HTTP_400_BAD_REQUEST)
                
                if field == 'cron':
                    if customizations[field] == True:
                        chatbox.subscription_type = 'cron'
                    else:
                        chatbox.subscription_type = ''

            chatbox.customizations = customizations
            chatbox.save()
            return Response({'status': 'Saved'}, status=status.HTTP_200_OK)
        
        except Exception as ex:
            print(ex)
            return Response(f"Error during saving bot customizations", status=status.HTTP_400_BAD_REQUEST)

#TODO: Remove This
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



class PublishChatbox(APIView):

    permission_classes = [IsAuthenticated]

    def get_object(self, pk):
        try:
            return Chatbox.objects.get(pk=pk, owner_id=self.request.user.pk)
        except Chatbox.DoesNotExist:
            raise Http404
    
    def get(self, request, pk, url_hash=None):

        query_params = request.query_params

        chatbox = self.get_object(pk)

        _status = "all"

        if 'status' in query_params:
            if query_params['status'] not in ('all', 'published', 'unpublished',):
                return Response(f"'status' query parameter must be one of ('all', 'published', 'unpublished')", status=status.HTTP_400_BAD_REQUEST)
            
            _status = query_params['status']
        
        if _status == 'all':
            # No filter
            if url_hash is None:
                queryset = ChatboxUrls.objects.filter(bot_hash=chatbox)
            else:
                queryset = ChatboxUrls.objects.filter(bot_hash=chatbox, url_hash=url_hash)
        else:
            if _status == 'published':
                if url_hash is None:
                    queryset = ChatboxUrls.objects.filter(bot_hash=chatbox, publish_status=True)
                else:
                    queryset = ChatboxUrls.objects.filter(bot_hash=chatbox, publish_status=True, url_hash=url_hash)
            else:
                if url_hash is None:
                    queryset = ChatboxUrls.objects.filter(bot_hash=chatbox, publish_status=False)
                else:
                    queryset = ChatboxUrls.objects.filter(bot_hash=chatbox, publish_status=False, url_hash=url_hash)

        serializer = ChatboxUrlSerializer(queryset, many=True)

        return Response(serializer.data, status=status.HTTP_200_OK)
                        
    def put(self, request, pk, url_hash=None):

        chatbox = self.get_object(pk)
        server_url = str(config('SERVER_URL'))
        try:
            sub_domain = str(config('SUB_SERVER_URL'))
            if sub_domain is not '':
                server_url = sub_domain + '.' + server_url
        except Exception as e:
            print(e)
        if 'website_url' not in request.data:
            return Response("website_url field is not present", status=status.HTTP_400_BAD_REQUEST)
        
        if 'allow_subdomain' not in request.data:
            request.data['allow_subdomain'] = False
        
        url = request.data['website_url']

        '''
        try:
            temp = url.split("://", 1)[1]
            if temp == '':
                temp = url
            url = temp
        except:
            return Response("URL is of an incorrect format", status=status.HTTP_400_BAD_REQUEST)
        '''

        try:
            # Hash the url to a hex value
            url_hash_bytes = binascii.hexlify(url.encode('utf-8'))
            url_hash = url_hash_bytes.decode('utf-8')
        except Exception as ex:
            print(ex)
            return Response("Error with URL encoding", status=status.HTTP_400_BAD_REQUEST)

        request.data['url_hash'] = url_hash
                
        request.data['js_file_path'] = f'https://{server_url}/widget/chatbox/bot_js/{pk}.js'
        
        request.data["bot_hash"] = chatbox

        serializer = ChatboxPublishSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        
        try:
            if request.data['publish_status'] is True:
                file_text = jsString.format(server_url, str(pk))
                
                cache.set(f"CLIENTWIDGET_TEMPLATE_{url}", str(pk), timeout=24 * 60 * 60)
                cache.set(f"CLIENTWIDGET_ALLOW_SUBDOMAINS_{url}", request.data['allow_subdomain'], timeout=24 * 60 * 60)
                
                # file_path = os.path.join('../widget', 'chatbox/bot_js', f'{pk}.js')
                # with open(file_path, 'w') as file_obj:
                #     file_obj.write(file_text)
                chatbox.publish(url, serializer.data['js_file_path'])
            else:
                cache.set(f"CLIENTWIDGET_TEMPLATE_{url}", False, timeout=24 * 60 * 60)
                cache.set(f"CLIENTWIDGET_ALLOW_SUBDOMAINS_{url}", request.data['allow_subdomain'], timeout=24 * 60 * 60)
                
                chatbox.publish(url, serializer.data['js_file_path'])
        
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Exception as ex:
            print(ex)
            return Response(f"Error during generating template file", status=status.HTTP_400_BAD_REQUEST)

    def post(self, request, pk, url_hash=None):

        chatbox = self.get_object(pk)
        server_url = str(config('SERVER_URL'))
        try:
            sub_domain = str(config('SUB_SERVER_URL'))
            if sub_domain is not '':
                server_url = sub_domain + '.' + server_url
        except Exception as e:
            print(e)
        if 'website_url' not in request.data:
            return Response("website_url field is not present", status=status.HTTP_400_BAD_REQUEST)

        if 'allow_subdomain' not in request.data:
            request.data['allow_subdomain'] = False
        
        url = request.data['website_url']

        try:
            # Hash the url to a hex value
            url_hash_bytes = binascii.hexlify(url.encode('utf-8'))
            url_hash = url_hash_bytes.decode('utf-8')
        except Exception as ex:
            print(ex)
            return Response("Error with URL encoding", status=status.HTTP_400_BAD_REQUEST)

        request.data['url_hash'] = url_hash
        
        request.data['js_file_path'] = f'https://{server_url}/widget/chatbox/bot_js/{pk}.js'
        request.data["bot_hash"] = chatbox

        serializer = ChatboxPublishSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        
        try:
            if request.data['publish_status'] is True:
                try:
                    cache.set(f"CLIENTWIDGET_TEMPLATE_{url}", str(pk), timeout=24 * 60 * 60)
                    cache.set(f"CLIENTWIDGET_ALLOW_SUBDOMAINS_{url}", request.data['allow_subdomain'], timeout=24 * 60 * 60)
                except Exception as ex:
                    print(ex)
                
                file_text = jsString.format(server_url, str(pk))
                # file_path = os.path.join('../widget', 'chatbox/bot_js', f'{pk}.js')
                # with open(file_path, 'w') as file_obj:
                #     file_obj.write(file_text)
                chatbox.publish(url, serializer.data['js_file_path'])
            else:
                try:
                    cache.set(f"CLIENTWIDGET_TEMPLATE_{url}", False, timeout=24 * 60 * 60)
                    cache.set(f"CLIENTWIDGET_ALLOW_SUBDOMAINS_{url}", request.data['allow_subdomain'], timeout=24 * 60 * 60)
                except Exception as ex:
                    print(ex)
                
                chatbox.publish(url, serializer.data['js_file_path'])
        
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Exception as ex:
            print(ex)
            return Response(f"Error during generating template file", status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk, url_hash=None):
        try:
            bot_hash = self.kwargs.get('pk')
            chatbox = Chatbox.objects.filter(bot_hash=bot_hash, owner=request.user.pk).first()
            if chatbox is None:
                return Response({'status':'Bot not found'}, status=status.HTTP_400_BAD_REQUEST)  
            
            try:
                if url_hash is None:
                    queryset = ChatboxUrls.objects.filter(bot_hash=chatbox)
                else:
                    queryset = ChatboxUrls.objects.filter(bot_hash=chatbox, url_hash=url_hash)
                    
                for instance in queryset:
                    cache.delete(f"CLIENTWIDGET_ALLOW_SUBDOMAINS_{instance.website_url}")
                    cache.delete(f"CLIENTWIDGET_TEMPLATE_{instance.website_url}")

                """
                for item in queryset.values('url_hash', 'website_url'):
                    url_hash = item['url_hash']
                    url = item['website_url']
                    
                    try:
                        cache.delete(f"CLIENTWIDGET_TEMPLATE_{url}")
                    except Exception as ex:
                        print(ex)
                    
                    file_location = os.path.join('widget', 'chatbox/bot_js', f'{bot_hash}_{url_hash}.js')
                    if os.path.exists(file_location):
                        os.remove(file_location)
                """
                queryset.delete()
            except Exception as e:
                print(e)
                return Response({'status': 'Something went wrong.'}, status=status.HTTP_400_BAD_REQUEST) 
            
            return Response({'status':'Deleted'}, status=status.HTTP_200_OK)    
        except Exception as e:
            print(e)
            return Response({'status': 'Something went wrong.'}, status=status.HTTP_400_BAD_REQUEST) 



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


class ClientMediaHandlerAPI(APIView):
    parser_classes = [parsers.MultiPartParser, parsers.FormParser, parsers.JSONParser]

    def post(self, request, room_id):
        try:
            media = dict(request.data)['media_file']
            media_list = []
            bot_owner = Chatbox.objects.get(pk=uuid.UUID(request.data['bot_id']))
            current_site = get_current_site(request)
            for med in media:
                media_handler = ClientMediaHandler(room_id=room_id,
                bot_id=request.data['bot_id'], media_file=med)
                media_handler.save(using=bot_owner.owner.ext_db_label)
                media_list.append("https://" + current_site.domain + media_handler.media_file.url)
            return Response(media_list)    
        except Exception as e:
            print(e)
            return Response({'status': 'Something went wrong.'}, 
            status=status.HTTP_400_BAD_REQUEST)



class AdminMediaHandlerAPI(APIView):
    parser_classes = [parsers.MultiPartParser, parsers.FormParser, parsers.JSONParser]

    def post(self, request, room_id):
        try:
            media = dict(request.data)['media_file']
            media_list = []
            bot_owner = Chatbox.objects.get(pk=uuid.UUID(request.data['bot_id']))
            current_site = get_current_site(request)
            for med in media:
                media_handler = AdminMediaHandler(room_id=room_id,
                bot_id=request.data['bot_id'], media_file=med)
                media_handler.save(using=bot_owner.owner.ext_db_label)
                media_list.append("https://" + current_site.domain + media_handler.media_file.url)
            return Response(media_list)    
        except Exception as e:
            print(e)
            return Response({'status': 'Something went wrong.'}, 
            status=status.HTTP_400_BAD_REQUEST)

        
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
            chatbox = get_object_or_404(Chatbox, bot_hash=bot_hash, owner=request.user.pk)
            prev_chatbox = chatbox.pk
            chatbox.pk = None
            chatbox.title = '(Copy)' + str(chatbox.title)
            chatbox.publish_status = False
            if chatbox.bot_variable_json is not None:
                chatbox.variable_columns = list(set(chatbox.bot_variable_json.keys()))
            else:
                chatbox.variable_columns = list()
            chatbox.save()
            ChatboxAppearance.objects.filter(chatbox__pk=chatbox.pk).delete()
            chatappearance = ChatboxAppearance.objects.get(chatbox__pk=prev_chatbox)
            chatappearance.pk = None
            chatappearance.chatbox = chatbox
            chatappearance.save()        
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
        chatbox = get_object_or_404(Chatbox, bot_hash=bot_hash, owner_id=request.user.pk)
        if chatbox.is_deleted:
            return Response({"status": "Already Deleted"}, status=status.HTTP_404_NOT_FOUND)
        else:
            return Response(ChatboxListSerializer(chatbox).data, status=status.HTTP_200_OK)    

    def delete(self, request, *args, **kwargs):
        try:
            bot_hash = self.kwargs.get('pk')
            chatbox = Chatbox.objects.filter(bot_hash=bot_hash, owner_id=request.user.pk).first()
            if chatbox is not None:
                chatbox.is_deleted = True
                chatbox.save()
            else:
                return Response({'status':'Deleted'}, status=status.HTTP_200_OK)
            
            file_location = os.path.join('../widget', 'chatbox/bot_js', f'{bot_hash}.js')
            if os.path.exists(file_location):
                os.remove(file_location)       
            
            try:
                queryset = ChatboxUrls.objects.filter(bot_hash=chatbox)
                for item in queryset.values('url_hash', 'website_url'):
                    url_hash = item['url_hash']
                    website_url = item['website_url']
                    # file_location = os.path.join('../widget', 'chatbox/bot_js', f'{bot_hash}_{url_hash}.js')
                    # if os.path.exists(file_location):
                    #     os.remove(file_location)
                    cache.delete(f"CLIENTWIDGET_ALLOW_SUBDOMAINS_{website_url}")
                    cache.delete(f"CLIENTWIDGET_TEMPLATE_{website_url}")
                queryset.delete()

            except Exception as e:
                print(e)
                return Response({'status': 'Something went wrong.'}, status=status.HTTP_400_BAD_REQUEST) 
            
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
        return TemplateChatbox.objects.filter(bot_hash=pk, is_deleted=False, owner_id=self.request.user.pk)


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


class ChatboxUrlListAPI(APIView):

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            chatbox = Chatbox.objects.get(pk=pk, owner_id=request.user.pk)
        except Chatbox.DoesNotExist:
            return Response("Bot ID not found", status=status.HTTP_404_NOT_FOUND)
        
        queryset = ChatboxUrls.objects.filter(bot_hash=chatbox).all()
        data = []
        for instance in queryset:
            data.append({'website_url': instance.website_url, 'publish_status': instance.publish_status})
        return Response(data, status=status.HTTP_200_OK)

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
    
    try:
        # Filter on domain with publish_status = True
        queryset = ChatboxUrls.objects.filter(bot_hash=chatbox, website_url=owner_website, publish_status=True)
        if queryset.exists():
            return HttpResponse(status=200)
        else:
            return HttpResponse(status=400)
    except Exception as ex:
        print(ex)
        return HttpResponse(status=400)

    return HttpResponse(status=400)


class BotLevelMetric(generics.GenericAPIView):

    def get(self, request, bot_id):

        if request.user.is_authenticated:
            bot_goal_completion = 0
            unique_chatrooms = 0
            bot_conversation = 0
            conversation_rate = 0
            goal_conversation_rate = 0
            date_from = None
            date_to = None

            if 'date_from' in request.query_params:
                date_from = request.query_params['date_from']
                date_from = datetime.strptime(date_from, "%Y-%m-%d")
                date_from = date_from - timedelta(minutes=request.user.utc_offset)
            if 'date_to' in request.query_params:
                date_to = request.query_params['date_to']
                date_to = datetime.strptime(date_to, "%Y-%m-%d")
                date_to = date_to - timedelta(minutes=request.user.utc_offset)

            try:
                if date_from is not None and date_to is not None:
                    chatrooms = ClientwidgetChatroom.objects.using(request.user.ext_db_label).filter(bot_id=bot_id,
                                                                                                    created_on__gte=date_from, created_on__lte=date_to + timedelta(days=1), admin_id=request.user.id)
                elif date_from is not None and date_to is None:
                    chatrooms = ClientwidgetChatroom.objects.using(request.user.ext_db_label).filter(bot_id=bot_id,
                                                                                                    created_on=date_from, admin_id=request.user.id)
                else:
                    chatrooms = ClientwidgetChatroom.objects.using(request.user.ext_db_label).filter(bot_id=bot_id, admin_id=request.user.id)

                bot_conversation = chatrooms.filter(is_lead=True).count()        
                unique_chatrooms = chatrooms.count()
                end_chat_chatrooms = chatrooms.filter(end_chat=True).count()
                
                if unique_chatrooms is not 0:
                    conversation_rate = (end_chat_chatrooms / unique_chatrooms) * 100

                for chatroom in chatrooms:
                    variable = dict(chatroom.variables)
                    if '@goal' in variable and variable['@goal'] == 'true':
                        bot_goal_completion+=1

                if unique_chatrooms is not 0:
                    goal_conversation_rate = (bot_goal_completion / unique_chatrooms) * 100

                return Response({'bot_goal_completion': bot_goal_completion,
                                'unique_bot_visits': unique_chatrooms,
                                'bot_conversations': bot_conversation,
                                'conversation_rate': "{:.2f}".format(conversation_rate),
                                'goal_conversation_rate': "{:.2f}".format(goal_conversation_rate)}, 
                                status=status.HTTP_200_OK)
                                            
            except Exception as e:
                print(e)
                return Response({'status': 'Something went wrong.'}, 
                                status=status.HTTP_400_BAD_REQUEST)
        else:
            return Response({'status': 'UNAUTHORIZED'}, 
                            status=status.HTTP_401_UNAUTHORIZED)            