"""Health-check routes (mounted at /health/ by config.urls)."""

from django.urls import path

from . import views

app_name = 'health'

urlpatterns = [
    path('live/', views.liveness, name='live'),
    path('ready/', views.readiness, name='ready'),
    path('celery/', views.celery_health, name='celery'),
]
