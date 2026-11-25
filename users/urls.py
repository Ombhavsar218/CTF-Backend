from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .throttling import LoginThrottle, TokenRefreshThrottle
from .views import (
    AvatarView,
    ChangePasswordView,
    LogoutView,
    MeView,
    OnboardingView,
    PreferencesView,
    RegisterView,
)


class ThrottledTokenObtainPairView(TokenObtainPairView):
    throttle_classes = [LoginThrottle]


class ThrottledTokenRefreshView(TokenRefreshView):
    throttle_classes = [TokenRefreshThrottle]


app_name = 'auth'

urlpatterns = [
    path('register/', RegisterView.as_view(), name='register'),
    path('login/', ThrottledTokenObtainPairView.as_view(), name='login'),
    path('refresh/', ThrottledTokenRefreshView.as_view(), name='refresh'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('password/', ChangePasswordView.as_view(), name='password-change'),
    path('me/', MeView.as_view(), name='me'),
    path('me/preferences/', PreferencesView.as_view(), name='me-preferences'),
    path('me/avatar/', AvatarView.as_view(), name='me-avatar'),
    path('onboarding/', OnboardingView.as_view(), name='onboarding'),
]
