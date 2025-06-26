from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils.timezone import now
from datetime import timedelta
from reminders.models import TaskManager
from reminders.task import notify_task
from celery import current_app

@receiver(post_save, sender=TaskManager)
def schedule_notify_task(sender, instance, created, **kwargs):
    # revoke 原本的任務（如果存在）
    if instance.celery_task_id:
        try:
            current_app.control.revoke(instance.celery_task_id, terminate=True)  # type: ignore
        except Exception as e:
            print(f"⚠️ Failed to revoke previous task with ID {instance.celery_task_id}: {e}")

    # 排程新的任務
    eta_time = now() + timedelta(seconds=instance.notify_interval)

    # 立即執行一次
    notify_task.delay(str(instance.uuid))  # type: ignore

    # 接著安排下一次
    result = notify_task.apply_async( # type: ignore
        args=[str(instance.uuid)],
        kwargs={'schedule_next': True},
        eta=eta_time
    )
    TaskManager.objects.filter(pk=instance.pk).update(
        celery_task_id=result.id,
        next_notify_time=eta_time,
        last_notified_at=now()
    )