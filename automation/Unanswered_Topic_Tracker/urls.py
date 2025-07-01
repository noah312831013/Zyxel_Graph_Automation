from django.urls import path
from .views import UnansweredTopicView,list_tasks,delete_task

urlpatterns = [
    path('unanswered/', UnansweredTopicView.as_view(), name='unanswered_topic'),
    path("api/list_tasks/", list_tasks, name="list_tasks"),
    path("api/delete_task<int:task_id>/", delete_task, name="delete_task"),
]