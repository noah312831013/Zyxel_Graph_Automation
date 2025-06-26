from django.urls import path
from .views import UnansweredTopicView

urlpatterns = [
    path('unanswered/', UnansweredTopicView.as_view(), name='unanswered_topic'),
]