from django.urls import path

from . import views

app_name = 'terminal'

urlpatterns = [
    path(
        'challenges/instances/terminal-ticket/',
        views.TerminalTicketView.as_view(),
        name='ticket-create',
    ),
]
