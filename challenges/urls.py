from django.urls import path

from .views import (
    ChallengeAttachmentDownloadView,
    ChallengeModeContentView,
    ChallengeSolutionView,
    PublicCategoryListView,
    PublicChallengeDetailView,
    PublicChallengeListView,
)

app_name = 'challenges_api'

urlpatterns = [
    path('challenges/', PublicChallengeListView.as_view(), name='challenge-list'),
    # Must precede the challenge-detail route so the extra path segment is not
    # swallowed by the detail pattern.
    path(
        'challenges/<int:pk>/attachments/<int:attachment_pk>/download/',
        ChallengeAttachmentDownloadView.as_view(),
        name='attachment-download',
    ),
    path(
        'challenges/<int:pk>/content/',
        ChallengeModeContentView.as_view(),
        name='challenge-mode-content',
    ),
    path(
        'challenges/<int:pk>/solution/',
        ChallengeSolutionView.as_view(),
        name='challenge-solution',
    ),
    path(
        'challenges/<int:pk>/',
        PublicChallengeDetailView.as_view(),
        name='challenge-detail',
    ),
    path('categories/', PublicCategoryListView.as_view(), name='category-list'),
]
