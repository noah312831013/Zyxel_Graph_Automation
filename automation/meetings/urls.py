from django.urls import path
from . import views

urlpatterns = [
    path('auto-schedule-meeting', views.schedule_meeting, name='auto_schedule_meeting'),
    path('webhook/response/', views.meeting_response, name='meeting_response'),
    path('meeting-status/<uuid:meeting_uuid>/', views.meeting_status, name='meeting_status'),
    path('api/contactors/', views.get_contacts, name='get_contacts'),
    path('api/list-meetings/', views.list_meetings, name='list_meetings'),
    path('meeting-progress/<uuid:meeting_uuid>/', views.meeting_progress_view, name='meeting_progress'),
    path('api/delete-meeting/<uuid:meeting_uuid>/', views.delete_meeting, name='delete_meeting'),

]