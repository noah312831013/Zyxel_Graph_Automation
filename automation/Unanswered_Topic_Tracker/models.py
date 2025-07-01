from django.db import models

class CeleryBeatTask_UTT(models.Model):
    celery_beat_task_id = models.AutoField(primary_key=True)
    chat_id = models.CharField(max_length=255)
    chat_name = models.CharField(max_length=255)
    host_id = models.CharField(max_length=255)
    sharepoint_path = models.CharField(max_length=1024)
    display_path = models.CharField(max_length=1024)

    frequency_minutes = models.IntegerField(default=60)  # 每幾分鐘跑一次
    is_active = models.BooleanField(default=True)        # 停用任務用
    result_question_ls = models.JSONField(null=True, blank=True)

    periodic_task = models.ForeignKey(
        "django_celery_beat.PeriodicTask",
        null=True, blank=True, on_delete=models.SET_NULL
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Task {self.celery_beat_task_id} for chat {self.chat_id}"
