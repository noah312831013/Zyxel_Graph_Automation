import logging
from celery import shared_task, Task
from django.utils.timezone import now
from datetime import timedelta, datetime
from reminders.models import TaskManager, TaskNotification
from reminders.sharepoint_client import GraphSharePointClient
import threading
from uuid import UUID

logger = logging.getLogger(__name__)

@shared_task
def notify_single_task(notification_id):
    try:
        notification = TaskNotification.objects.get(uuid=notification_id)
        sharepoint_client = GraphSharePointClient(notification.host_id)
        sharepoint_client.notify(notification)
    except Exception as e:
        logger.error(f"notify_task：Notification failed for {notification_id}: {e}")
        
@shared_task
def notify_task(uuid_str:str, schedule_next: bool = False):
    try:
        task = TaskManager.objects.get(uuid=UUID(uuid_str))
        sharepoint_client = GraphSharePointClient(task.host_id)
        try:
            # 爬一次以免沒爬到訊息
            sharepoint_client.scrum()
        except Exception as e:
            logger.error(f"Scrum failed: {e}")

        notifications = TaskNotification.objects.filter(
            host_id=task.host_id,
            site_name=task.site_name,
            drive_name=task.drive_name,
            file_path=task.file_path,
        ).exclude(status=TaskNotification.Status.COMPLETED)

        # 發通知
        for notification in notifications:
            notify_single_task.delay(notification.uuid)  # type: ignore

        logger.info(f"notification pushed {task.file_path}")

        if schedule_next:
            # 更新下一次提醒時間
            next_time = now() + timedelta(seconds=task.notify_interval)
            result = notify_task.apply_async((str(task.uuid),), eta=next_time) # type: ignore
            TaskManager.objects.filter(pk=task.pk).update(
                celery_task_id=result.id,
                next_notify_time=next_time,
                last_notified_at=now()
            )
            logger.info(f"{'='*5} setup for next time {result.id} {next_time}")
    except Exception as e:
        logger.error(f"notify_task failed for uuid {uuid_str}: {e}")