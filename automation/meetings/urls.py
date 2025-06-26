from django.urls import path
from . import views

urlpatterns = [
    path('auto-schedule-meeting', views.schedule_meeting, name='auto_schedule_meeting'),
    path('webhook/response/', views.meeting_response, name='meeting_response'),
    path('meeting-status/<uuid:meeting_uuid>/', views.meeting_status, name='meeting_status'),
    path('api/contactors/', views.get_contacts, name='get_contacts'),
]