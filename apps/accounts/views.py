from rest_framework import generics, permissions, status
from rest_framework.response import Response
from .serializers import UserSerializer, RegisterSerializer, LoginSerializer, UserRegSerializer, ChangePasswordSerializer, UserProfileSerializer, GoogleSocialAuthSerializer,\
ResetPasswordSerializer, ResetPasswordConfirm, TokenSerializer, DummySerializer, UpdateProfilePicSerializer, UserSerializerWithAvatar
from django.contrib.auth import authenticate, login, logout
from .models import User
from rest_framework.parsers import MultiPartParser, FileUploadParser, JSONParser, FormParser
from PIL import Image
from rest_framework.views import APIView
from rest_framework.exceptions import ParseError
from django.contrib.sites.shortcuts import get_current_site
from django.core.mail import EmailMessage, send_mail
from django.template.loader import render_to_string
from django.utils.encoding import force_bytes, force_text
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.conf import settings
from rest_framework.authentication import BasicAuthentication
from django.core.mail import EmailMessage
from django.core.mail.message import EmailMultiAlternatives
from apps.permission.models import PermissionRouting
from apps.permission import permission_json
from .task import acc_email_send, email_alternative



# Check Authorization API
class CheckAuthorization(generics.GenericAPIView):
  serializer_class = DummySerializer
  def get(self, request):
    if self.request.user.is_authenticated:
      return Response(status=status.HTTP_200_OK)
    else:
      return Response(status=status.HTTP_401_UNAUTHORIZED)



# Register API
class RegisterAPI(generics.GenericAPIView):
  '''
  Used for resgistering the user
  Fields: email, password, first_name
  Endpoint: api/auth/register
  '''
  serializer_class = RegisterSerializer
  authentication_classes = (BasicAuthentication,)
  permission_classes = (permissions.AllowAny,)
  
  def post(self, request, *args, **kwargs):
    serializer = self.get_serializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    user = serializer.save()
    current_site = get_current_site(request)
    mail_subject = 'Activate your Autovista Chatbot account.'
    message = render_to_string('acc_active_email.html', {
        'user': user,
        'domain': current_site.domain,
        'uid':urlsafe_base64_encode(force_bytes(user.pk)),
        'token':account_create_token.make_token(user),
    })
    to_email = user.email
    print(to_email)
    acc_email_send.delay(mail_subject, message, to_email)
    # email = EmailMessage(mail_subject, message, to=[to_email])
    # email.send()
    return Response({'status': 'Check Your Email',
                    }, status=status.HTTP_200_OK)



class ActivateEmail(generics.GenericAPIView):
  serializer_class = DummySerializer
  '''
  Used for activating the account
  Email will be send to the user with uid and token
  Endpoint: api/activate/(?P<uidb64>[0-9A-Za-z_\-]+)/(?P<token>[0-9A-Za-z]{1,13}-[0-9A-Za-z]{1,20})
  '''

  def get(self, request, uidb64, token):
    try:
      uid = force_text(urlsafe_base64_decode(uidb64))
      user = User.objects.get(pk=uid)
    except Exception as e:
        user = None
    if user is not None and account_create_token.check_token(user, token):
        user.is_active = True
        user.save()
        #login(request, user)
        return Response({
        "user": UserRegSerializer(user).data,
        }, status=status.HTTP_200_OK)
    else:
      return Response({
        'status': 'Token Expired'
      }, status=status.HTTP_406_NOT_ACCEPTABLE)


#ResetPassword
class ResetPasswordClass(generics.GenericAPIView):
  '''
  Api used for resetting the password. 
  Input: email
  Endpoint: api/auth/password_reset
  '''
  serializer_class = ResetPasswordSerializer

  def post(self, request, *args, **kwargs):
    to_email = request.data['email']
    try:
      user = User.objects.get(email=to_email)
      if user is not None:
        if user.is_active == False:
          return Response({'status': 'User Not Active'}, status=status.HTTP_404_NOT_FOUND)
        current_site = get_current_site(request)
        mail_subject = 'Reset your Autovista Chatbot account Password'
        message = render_to_string('pass_active_email.html', {
            'user': user,
            'domain': current_site.domain,
            'uid':urlsafe_base64_encode(force_bytes(user.pk)),
            'token':account_create_token.make_token(user),
        })
        acc_email_send.delay(mail_subject, message, to_email)
        # email = EmailMessage(mail_subject, message, to=[to_email])
        # email.send()
        return Response({'status': 'Email Send'}, status=status.HTTP_200_OK)
    except User.DoesNotExist:
      return Response({'status': 'User does not exists'}, status=status.HTTP_404_NOT_FOUND)    


class ResetConfirmPasswordClass(generics.GenericAPIView):
     '''
     Email will be send to user with uid and token.
     Endpoint: api/reset_password/(?P<uidb64>[0-9A-Za-z_\-]+)/(?P<token>[0-9A-Za-z]{1,13}-[0-9A-Za-z]{1,20})
     '''
     serializer_class = ResetPasswordConfirm 

     def post(self, request, uidb64, token):
       try:
         uid = force_text(urlsafe_base64_decode(uidb64))
         user = User.objects.get(pk=uid)
       except Exception:
         user = None
       if user is not None and custom_reset_password_token.check_token(user, token):
          print(user)
          if request.data['password'] == request.data['re_password']:
            user.set_password(request.data['password'])
            user.save()
            return Response({'status': 'Password Changed'}, status=status.HTTP_200_OK)
          else:  
            return Response({'status': 'Password did not match'}, status=status.HTTP_417_EXPECTATION_FAILED)  
       else:
         return Response({'status': "Token Expired"}, status=status.HTTP_406_NOT_ACCEPTABLE)
               


# Login API
class LoginAPI(generics.GenericAPIView):
  '''
  LoginApi used for authentication.
  Fields: email, password
  Endpoint: api/auth/login
  '''
  serializer_class = LoginSerializer

  def post(self, request, *args, **kwargs):
    serializer = self.get_serializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    user = serializer.validated_data
    login(request, user)
    try:
      permission_routing = PermissionRouting.objects.get(user=request.user)
      return Response({

        "user": UserSerializer(user, context=self.get_serializer_context()).data,
        "permission_routing": permission_routing.routes,
        "navbar_routing": permission_routing.nav_routes,

      }, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({
        "user": UserSerializer(user, context=self.get_serializer_context()).data,
      }, status=status.HTTP_200_OK)


# LogoutView API
class LogoutView(generics.GenericAPIView):
  '''
  Logout Api.
  Destroy the session.
  Endpoint: api/auth/logout
  '''
  serializer_class = DummySerializer
  def get(self, request):
    try:
      if request.user.role in ['AO']:
        user = request.user
        user.can_takeover = False
        user.save()
      logout(request)
      return Response({
        "status": "Log Out",
      }, status=status.HTTP_200_OK)
    except Exception as e:
      print(e)
      return Response({
        "status": "Something Went Wrong",
      }, status=status.HTTP_406_NOT_ACCEPTABLE)



# User Profile Update
class UserProfile(generics.RetrieveUpdateAPIView):
    '''
    User Profile api for CRUD operation.
    Endpoint: api/auth/user/<int:pk>
    '''
    serializer_class = UserProfileSerializer
    permission_classes = [permissions.IsAuthenticated,]
    parser_classes = [MultiPartParser, JSONParser, FormParser]
    
    def get_queryset(self):
      pk = self.kwargs.get('pk')
      user = User.objects.filter(id=pk, is_active=True, user_is_deleted=False)
      return user  


# Image Upload APis
class ImageUploadParser(FileUploadParser):
    '''
    Image Upload Parser Class
    '''
    media_type = 'image/*'


class UpdateProfilePic(generics.GenericAPIView):
  '''
  Image Upload Api
  Endpoint: api/auth/profile_pic/update
  '''
  serializer_class = UpdateProfilePicSerializer
  parser_classes = [ImageUploadParser, MultiPartParser, JSONParser]
  # permission_classes = [permissions.IsAuthenticated,]

  def get_serializer_context(self):
    context = super(UpdateProfilePic, self).get_serializer_context()
    context['current_request'] = self.request
    return context

  def put(self, request):
    if 'avatar' in request.data:
      user = request.user
      file = request.data['avatar']
      site = get_current_site(request)
      print(site)
      # Can use pillow in future for cropping and verifying the image
      # try:
      #   avatar = Image.open(file)
      #   avatar.verify()
      # except ParseError:
      #   raise ParseError('Unsupported Image Type')
      user.avatar.save(file.name, file, save=True)
      return Response({"user": UserSerializerWithAvatar(user, context=self.get_serializer_context()).data}, status=status.HTTP_200_OK)
    else:
      return Response(status=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE)    


# Get User API
class UserAPI(generics.RetrieveUpdateAPIView):
  '''
  Profile CRUD operation apis
  Endpioint: api/auth/user/
  '''
  # permission_classes = [
  #   permissions.IsAuthenticated,
  # ]
  serializer_class = UserSerializerWithAvatar  

  def get(self, request):
    if request.user.is_authenticated and not request.user.user_is_deleted:
      serialized_data = UserSerializerWithAvatar(request.user)
      return Response(serialized_data.data)
    else:
      return Response(status=status.HTTP_401_UNAUTHORIZED)

  def get_object(self):
    return self.request.user


# Change Password
class ChangePasswordAPI(generics.GenericAPIView):
  '''
  Change Password api
  Will send the password on user email once changed
  Endpoint: api/auth/change_password
  '''
  serializer_class = ChangePasswordSerializer
  permission_classes = [permissions.IsAuthenticated,]

  def get_serializer_context(self):
    context = super(ChangePasswordAPI, self).get_serializer_context()
    context.update({'user': self.request.user})
    return context


  def post(self, request, *args, **kwargs):
      serializer = self.get_serializer(data = request.data)
      serializer.is_valid(raise_exception=True)
      user = serializer.validated_data
      login(request, user)
      mail_subject = 'Your Autovista Chatbot account Password has been Changed'
      message = render_to_string('pass_changed.html', {
          'password': request.data['password']
      })
      to_email = request.user.email
      acc_email_send.delay(mail_subject, message, to_email)
      # email = EmailMessage(mail_subject, message, to=[to_email])
      # email.send()
      return Response(UserSerializer(user).data, status=status.HTTP_200_OK)

# Reset Password
from django.core.mail import EmailMultiAlternatives
from django.dispatch import receiver
from django.template.loader import render_to_string
from django.urls import reverse

from django_rest_passwordreset.signals import reset_password_token_created


@receiver(reset_password_token_created)
def password_reset_token_created(sender, instance, reset_password_token, *args, **kwargs):
    """
    Handles password reset tokens
    When a token is created, an e-mail needs to be sent to the user
    :param sender: View Class that sent the signal
    :param instance: View Instance that sent the signal
    :param reset_password_token: Token Model Object
    :param args:
    :param kwargs:
    :return:
    """
    # send an e-mail to the user
    context = {
        'current_user': reset_password_token.user,
        'email': reset_password_token.user.email,
        'reset_password_url': "{}?token={}".format(reverse('password_reset:reset-password-request'), reset_password_token.key)
    }

    # render email text
    email_html_message = render_to_string('email/user_reset_password.html', context)
    email_plaintext_message = render_to_string('email/user_reset_password.txt', context)

    msg = EmailMultiAlternatives(
        # title:
        "Password Reset for {title}".format(title="Some website title"),
        # message:
        email_plaintext_message,
        # from:
        "noreply@somehost.local",
        # to:
        [reset_password_token.user.email]
    )
    msg.attach_alternative(email_html_message, "text/html")
    msg.send()


# Token Generator
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.utils import six

class TokenGenerator(PasswordResetTokenGenerator):
  def _make_hash(self, user, timestamp):
    return (
      six.text_type(user.pk) + six.text_type(timestamp) + six.text_type(user.is_active)
    )
account_create_token = TokenGenerator()    
custom_reset_password_token = TokenGenerator()


class CanTakeoverAPI(APIView):

  def post(self, request):
    try:
      user = request.user
      if user.role in ['AO']:
        user.can_takeover = request.data['is_available']
        user.save()
        return Response({'is_available': user.can_takeover, 
                        'status': 'Success'})
      else:
        return Response({'status': 'User should be Operator'}, status=status.HTTP_406_NOT_ACCEPTABLE)
    except Exception as e:
      return Response({'status': 'Something Went Wrong. Contact Backend'}, status=status.HTTP_404_NOT_FOUND)

  def get(self, request):
    return Response({'is_available': request.user.can_takeover,
                    'status': 'Success'})




              


    

