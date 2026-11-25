from django.urls import path

from .views import AdminPlatformSettingsView

app_name = 'platform_settings_admin'

urlpatterns = [
    path(
        'settings/',
        AdminPlatformSettingsView.as_view(),
        name='platform-settings',
    ),
]
