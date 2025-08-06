import logging
from celery import shared_task
from reminders.models import TaskManager, TaskNotification
from reminders.sharepoint_client import GraphSharePointClient
import time
from datetime import timedelta
from django.utils import timezone
logger = logging.getLogger(__name__)

# @shared_task
# def notify_single_task(notification_id):
#     try:
#         notification = TaskNotification.objects.get(uuid=notification_id)
#         sharepoint_client = GraphSharePointClient(notification.host_id)
#         sharepoint_client.notify(notification)
#     except Exception as e:
#         logger.error(f"notify_task：Notification failed for {notification_id}: {e}")

import random
MAX_NOTIFICATIONS_PER_BATCH = 2
SLEEP_BETWEEN_BATCHES = 2  # 秒數，避免 hitting rate limit
@shared_task(bind=True, max_retries=5)
def notify_single_task(self, notification_id):
    try:
        notification = TaskNotification.objects.get(uuid=notification_id)
        sharepoint_client = GraphSharePointClient(notification.host_id)
        sharepoint_client.notify(notification)
    except Exception as e:
        if "Too Many Requests" in str(e):  # 你也可以更精準用 API 回傳 code 判斷
            countdown = random.randint(30, 60)  # 加上隨機退避避免擠在同一時間
            logger.warning(f"Rate limit hit. Retrying in {countdown} seconds.")
            self.retry(exc=e, countdown=countdown)
        else:
            logger.error(f"notify_task：Notification failed for {notification_id}: {e}")

@shared_task
def notify_task(uuid):
    try:
        task = TaskManager.objects.get(uuid=uuid)
        sharepoint_client = GraphSharePointClient(task.host_id)
        try:
            # 爬一次以免沒爬到訊息
            sharepoint_client.scanAnyMatchMsg()
        except Exception as e:
            logger.error(f"scanAnyMatchMsg failed: {e}")

        notifications = TaskNotification.objects.filter(
            host_id=task.host_id,
            site_name=task.site_name,
            drive_name=task.drive_name,
            file_path=task.file_path,
        ).exclude(status=TaskNotification.Status.COMPLETED)

        for i, notification in enumerate(notifications):
            notify_single_task.delay(notification.uuid) # type: ignore
        task.last_notified_at = timezone.now()
        task.next_notify_time = task.last_notified_at + timedelta(minutes=task.notify_interval)
        task.save()
        logger.info(f"notification pushed {task.file_path}")
    except Exception as e:
        logger.error(f"notify_task failed for uuid {uuid}: {e}")
@shared_task 
def daemon_task():
    """
    Background daemon that scans SharePoint messages for each unique host_id in TaskNotification.
    Scheduled using Celery Beat (e.g., via CrontabSchedule).
    """
    # Get all distinct host_ids from TaskNotification
    host_ids = TaskNotification.objects.values_list('host_id', flat=True).distinct()
    for host_id in host_ids:
        print(f"Running daemon scan for host_id: {host_id}")
        client = GraphSharePointClient(user_id=host_id)
        client.scanAnyMatchMsg()