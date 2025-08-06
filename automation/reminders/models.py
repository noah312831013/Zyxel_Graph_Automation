from django.db import models
import uuid
from django_celery_beat.models import PeriodicTask

# Create your models here.
# 舊的
class TaskNotification(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        SENT = "SENT", "Sent"
        FAILED = "FAILED", "Failed"
        COMPLETED = "COMPLETED", "Completed"

    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)  # 新增 UUID 欄位
    site_name = models.CharField(max_length=255)
    drive_name = models.CharField(max_length=255)
    file_path = models.CharField(max_length=255)
    sheet_name = models.CharField(max_length=255)
    teams_group_id = models.CharField(max_length=255)
    teams_group_name = models.CharField(max_length=255)
    row = models.IntegerField()
    task = models.CharField(max_length=255)
    owner_id = models.CharField(max_length=255, null=True, blank=True, default=None)
    owner_email = models.EmailField(null=True, blank=True, default=None)
    owner_name = models.CharField(max_length=255, null=True, blank=True, default="Unknown Owner")
    field_address = models.CharField(max_length=255)
    reason = models.CharField(max_length=255)
    msg_id = models.JSONField(default=list)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING
    )    
    created_at = models.DateTimeField(auto_now_add=True)
    host_id = models.CharField(max_length=255)

    def __str__(self):
        return f"{self.sheet_name} - Row {self.row}: {self.task}"

class TaskManager(models.Model):
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True,primary_key=True)  # 新增 UUID 欄位
    celery_task_id = models.CharField(max_length=255, null=True, blank=True, default=None)
    site_name = models.CharField(max_length=255)
    drive_name = models.CharField(max_length=255)
    file_path = models.CharField(max_length=255)
    sheet_name = models.CharField(max_length=255, null=True, blank=True, default=None)
    notify_interval = models.IntegerField(default=60)  # in min
    last_notified_at = models.DateTimeField(null=True, blank=True,default=None)
    next_notify_time = models.DateTimeField(null=True, blank=True,default=None)
    host_id = models.CharField(max_length=255)
    periodic_task = models.ForeignKey(
        PeriodicTask,
        null=True,
        blank=True,
        on_delete=models.SET_NULL
    )