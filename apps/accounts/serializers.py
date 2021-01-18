from rest_framework import serializers
from .models import User
from django.contrib.auth import authenticate
from rest_framework.authtoken.models import Token
from django.contrib.sites.shortcuts import get_current_site
from decouple import config


class UserOwnerSerializers(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('uuid',)


# Register
class UserRegSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id', 'email','role','first_name', 'last_name')

# User Serializer
class UserSerializer(serializers.ModelSerializer):
    # role_name = serializers.CharField(source='role.name')
    created_by = UserOwnerSerializers(read_only=True)
    class Meta:
        ref_name = "UserSerializer"
        model = User
        fields = ('id' ,'email','first_name', 'last_name', 'phone_number', 'avatar', 'website', 'city', 'address', 'state', 'zipcode', 'country', 'role', 'google_granted_acc', 'uuid', 'created_by', 'ext_db_label')


# User Profile Serializer
class UserProfileSerializer(serializers.ModelSerializer):
    # role_name = serializers.CharField(source='role.name')
    created_by = UserOwnerSerializers(read_only=True)
    class Meta:
        model = User
        fields = ('first_name', 'last_name','email', 'phone_number', 'avatar', 'website', 'city', 'address', 'state', 'zipcode', 'country', 'google_granted_acc', 'uuid', 'created_by', 'ext_db_label')

# Register Serializer
class RegisterSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id', 'email', 'password','first_name', 'last_name')
        extra_kwargs = {'password': {'write_only': True}}

    def create(self, validated_data):
        
        user = User.objects.create_user(email= validated_data['email'],
                                         password = validated_data['password'],
                                         first_name = validated_data['first_name'],
					 last_name = validated_data['last_name'],
                                         role='AM', is_active=False, utc_offset=+330)
        return user

# Login Serializer
class LoginSerializer(serializers.Serializer):
    email = serializers.CharField()
    password = serializers.CharField()
    utc_offset = serializers.IntegerField(default=+330) # +5:30

    def validate(self, data):
        utc_offset = data['utc_offset']
        
        user = authenticate(**data)
        if user and user.is_active and not user.user_is_deleted:
            try:
                if user.utc_offset != utc_offset:
                    user.utc_offset = utc_offset
                    user.save()
            except:
                pass
            return user
        raise serializers.ValidationError("Incorrect Credentials")

# Change Password
class ChangePasswordSerializer(serializers.Serializer):
    password = serializers.CharField()
    re_password = serializers.CharField()

    def validate(self, data):
        user = self.context['user']
        if user and user.is_active:
            if data['password'] == data['re_password']:
                user.set_password(data['password'])
                user.save()
                return user
            else:
                raise serializers.ValidationError('Password didn\'t match !')    
        raise serializers.ValidationError("Incorrect Credentials")


# Social Auth
class GoogleSocialAuthSerializer(serializers.ModelSerializer):

    token = serializers.SerializerMethodField('get_user_token')

    def get_user_token(self, obj):
        token, created = Token.objects.get_or_create(user=obj.user)
        return token.key

    class Meta:
        model = User

#Reset Password
class ResetPasswordSerializer(serializers.Serializer):

    email = serializers.EmailField()

class ResetPasswordConfirm(serializers.Serializer):
    password = serializers.CharField()
    re_password = serializers.CharField()

    def validate(self, data):
        user = self.context['user']
        if data['password'] == data['re_password']:
            user.set_password(data['password'])
            user.save()
            return user
        else:
            return None


class TokenSerializer(serializers.Serializer):
    token = serializers.CharField()

    class Meta:
        ref_name = "TokenSerializer"


# Serializer for the class which don't need serializer
class DummySerializer(serializers.Serializer):
    class Meta:
        ref_name = 'DummySerializer'


class UpdateProfilePicSerializer(serializers.Serializer):
    avatar = serializers.ImageField()


# User Serializer
class UserSerializerWithAvatar(serializers.ModelSerializer):
    # role_name = serializers.CharField(source='role.name')
    avatar = serializers.SerializerMethodField('get_full_url_avatar')
    role = serializers.CharField(read_only=True)
    created_by = UserOwnerSerializers(read_only=True)
    team_name = serializers.SerializerMethodField('get_team')
    def get_full_url_avatar(self, obj):
        if obj.avatar:
            site = config('SERVER_URL')
            return 'https://' + site + obj.avatar.url
        else:
            return None

    def get_team(self, obj):
        if obj.team_member is not None:
            return obj.team_member.name
        else:
            return ''    

    class Meta:
        model = User
        # fields = ('id', 'email', 'role')

        fields = ('id' ,'email','first_name', 'last_name', 'phone_number', 'avatar', 'website', 'city', 'address', 'state', 'zipcode', 'country', 'role', 'google_granted_acc', 'uuid', 'created_by', 'can_takeover', 'team_name')



