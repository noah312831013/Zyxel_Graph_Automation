from django.urls import path
from . import views

urlpatterns = [
    # path("sharepoint-reminder/", views.sharepoint_reminder_dashboard, name="sharepoint_reminder_dashboard"),
    # path("add_schedule_task/", views.add_schedule_task, name="add_schedule_task"),
    # path("stop-tasks/", views.stop_tasks, name="stop_tasks"),
    path("sharepoint-reminder/", views.SharePointReminderDashboardView.as_view(), name="sharepoint_reminder_dashboard"),
    path("get-tracking-items/", views.get_tracking_items, name="get_tracking_items"),
    path("task_notifications/", views.get_task_notifications, name='get_task_notifications'),
    path('delete_task/', views.delete_task, name='delete_task'),
]