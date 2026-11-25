from django.urls import path

from . import views

app_name = 'instances'

urlpatterns = [
    path('challenges/<int:pk>/instances/start/', views.InstanceStartView.as_view(), name='instance-start'),
    path('challenges/instances/active/', views.InstanceActiveView.as_view(), name='instance-active'),
]
