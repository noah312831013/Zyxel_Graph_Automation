from django.urls import path
from . import views

urlpatterns = [
    path("sharepoint-reminder/", views.sharepoint_reminder_dashboard, name="sharepoint_reminder_dashboard"),
    path("add_schedule_task/", views.add_schedule_task, name="add_schedule_task"),
    # path("stop-tasks/", views.stop_tasks, name="stop_tasks"),
    path("get-tracking-items/", views.get_tracking_items, name="get_tracking_items"),
]