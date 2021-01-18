from django.urls import path, include

from .views import RegisterAPI, LoginAPI, UserAPI, ChangePasswordAPI, LogoutView, UserProfile,\
	 UpdateProfilePic, ActivateEmail, ResetPasswordClass, ResetConfirmPasswordClass, \
		 CheckAuthorization, CanTakeoverAPI

from django.conf.urls import url

urlpatterns = [
	
	path('auth/register', RegisterAPI.as_view()),
	path('auth/login', LoginAPI.as_view()),
	path('auth/user', UserAPI.as_view()),
	path('auth/user/profile/<int:pk>', UserProfile.as_view()),
	path('auth/profile_pic/update', UpdateProfilePic.as_view()),
	path('auth/change_password', ChangePasswordAPI.as_view()),
	path('auth/logout', LogoutView.as_view()),
	path('auth/password_reset', ResetPasswordClass.as_view()),
	path('auth/check', CheckAuthorization.as_view()),
	path('auth/can_takeover', CanTakeoverAPI.as_view()),

	url(r'^password_reset/', include('django_rest_passwordreset.urls', namespace='password_reset')),
	url(r'^activate/(?P<uidb64>[0-9A-Za-z_\-]+)/(?P<token>[0-9A-Za-z]{1,13}-[0-9A-Za-z]{1,20})/$',
        ActivateEmail.as_view(), name='activate'),
	url(r'^reset_password/(?P<uidb64>[0-9A-Za-z_\-]+)/(?P<token>[0-9A-Za-z]{1,13}-[0-9A-Za-z]{1,20})/$',
        ResetConfirmPasswordClass.as_view(), name='custom_password_reset'),	

]
