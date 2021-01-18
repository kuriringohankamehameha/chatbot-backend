from django.urls import path

from . import views

urlpatterns = [
     path('clientwidget/demo', views.index, name='client widget demo index'),
     path('clientwidget/demo/<str:room_name>/', views.room, name='client widget demo room'),
]
