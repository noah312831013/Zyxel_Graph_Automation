from django.shortcuts import render
from core.views import initialize_context
from django.http import HttpResponseRedirect, JsonResponse
from django.urls import reverse
from .sharepoint_client import GraphSharePointClient
import time
from .models import TaskNotification, TaskManager
from django.views import View
from django import forms
from core.teams_client import TeamsClient
from django_celery_beat.models import IntervalSchedule, PeriodicTask, CrontabSchedule
from .tasks import notify_task,daemon_task
import json


def schedule_notify(task: TaskManager):
    # 建立或取得 CrontabSchedule
    schedule, _ = CrontabSchedule.objects.get_or_create(
        minute=f"*/{task.notify_interval}",
        hour='8-19',
        day_of_week='*',
        day_of_month='*',
        month_of_year='*'
    )

    task_name = f"sharepoint-notify-{task.uuid}"

    # 檢查是否已存在同名的 PeriodicTask
    periodic_task = PeriodicTask.objects.filter(name=task_name).first()

    if periodic_task:
        # 🔁 更新原有任務
        periodic_task.crontab = schedule
        periodic_task.args = json.dumps([str(task.pk)])
        periodic_task.task = 'reminders.tasks.notify_task'
        periodic_task.enabled = True
        periodic_task.save()
        task.periodic_task = periodic_task # type: ignore
    else:
        # 🆕 新增任務
        periodic_task = PeriodicTask.objects.create(
            crontab=schedule,
            name=task_name,
            task='reminders.tasks.notify_task',
            args=json.dumps([str(task.pk)]),
        )
        task.periodic_task = periodic_task # type: ignore

    task.save()
    notify_task.delay(str(task.pk))  # type: ignore # 立即非同步執行一次


# Register daemon_task as a periodic task in Celery Beat
def schedule_daemon_task():
    # Run every 30 minutes as an example
    schedule, _ = CrontabSchedule.objects.get_or_create(
        minute="*/30",
        hour="*",
        day_of_week="*",
        day_of_month="*",
        month_of_year="*"
    )

    task_name = "reminders.tasks.daemon-task-scan"

    periodic_task, created = PeriodicTask.objects.get_or_create(
        name=task_name,
        defaults={
            'crontab': schedule,
            'task': 'reminders.tasks.daemon_task',  # Adjust if you move daemon_task to another file
        }
    )

    if not created:
        periodic_task.crontab = schedule
        periodic_task.task = 'reminders.views.daemon_task'
        periodic_task.enabled = True
        periodic_task.save()

class driveForm(forms.Form):
    drive_name = forms.ChoiceField(label="SharePoint Drive Name", initial="ScrumSprints",required=True)
    file_path = forms.CharField(label="File Path", initial="Feature to do list+Q&A/[19.10] Mx Feature_to do list+ Q&A.xlsx", max_length=1024,required=True)
    frequency = forms.IntegerField(label="notify interval time", min_value=1, initial=60*8,required=True)
    sheet_name = forms.CharField(label="Sheet Name", initial='automation_test', max_length=1024, required=False)
    def __init__(self, *args, **kwargs):
        drive_names = kwargs.pop('drive_names', [])
        super().__init__(*args, **kwargs)
        self.fields["drive_name"].choices = [(dn, dn) for dn in drive_names]
        # 加上 Bootstrap class="form-control"
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'form-control'})

class SharePointReminderDashboardView(View):
    template_name = "sharepoint_reminder_dashboard.html"
    def get(self, request):
        context = initialize_context(request)
        user = context['user']
        if not user['is_authenticated']:
            return HttpResponseRedirect(reverse('signin'))
        gp=TeamsClient(user['id'])
        site_name = "NebulaP8group"
        drive_names = gp.list_drive(site_name)
        form = driveForm(drive_names=drive_names)
        context['form'] = form
        return render(request, self.template_name, context)
    def post(self, request):
        context = initialize_context(request)
        user = context['user']
        if not user['is_authenticated']:
            return HttpResponseRedirect(reverse('signin'))
        form = driveForm(request.POST, drive_names=GraphSharePointClient(user_id=user['id']).list_drive("NebulaP8group"))
        if form.is_valid():
            drive_name = form.cleaned_data['drive_name']
            file_path = form.cleaned_data['file_path']
            sheet_name = form.cleaned_data['sheet_name']
            frequency = form.cleaned_data['frequency']
            gp = GraphSharePointClient(user_id=user['id'],drive_name=drive_name,path=file_path)
            task=gp.create_notify_items(notify_interval=frequency, sheet_name=sheet_name)
            schedule_notify(task)
            return HttpResponseRedirect(reverse('sharepoint_reminder_dashboard'))
        context['form'] = form
        return render(request, self.template_name, context)

from urllib.parse import unquote,quote

def get_tracking_items(request):
    """
    Returns the list of task managers for real-time updates.
    """
    items = TaskManager.objects.filter(host_id=request.session['user']['id']).values(
         "drive_name", "file_path", "notify_interval", "last_notified_at", "next_notify_time"
    )
    # 對 file_path 解碼，並加上通知查詢 url
    result = []
    for item in items:
        item["notification_url"] = f"/reminders/task_notifications/?file_path={item['file_path']}"
        item["file_path"] = unquote(item["file_path"])
        # 加入通知查詢的 url
        result.append(item)
    return JsonResponse(result,safe=False)

from django.views.decorators.http import require_GET

@require_GET
def get_task_notifications(request):
    """
    根據 file_path 查詢 TaskNotification，回傳通知紀錄。
    GET 參數: file_path
    """
    context = initialize_context(request)
    if not context['user']['is_authenticated']:
        return HttpResponseRedirect(reverse('signin'))
    file_path = request.GET.get("file_path")
    print(f"file_path: {file_path}")
    if not file_path:
        return JsonResponse({"error": "Missing file_path"}, status=400)
    notifications = TaskNotification.objects.filter(
    host_id=request.session['user']['id'],file_path=quote(file_path))
    context['notifications'] = notifications
    return render(request, "notification_records.html", context)
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from .models import TaskNotification, TaskManager

@csrf_exempt
def delete_task(request):
    context = initialize_context(request)
    if not context['user']['is_authenticated']:
        return HttpResponseRedirect(reverse('signin'))
    if request.method == "POST":
        drive_name = request.POST.get("drive_name")
        file_path = quote(request.POST.get("file_path"))
        # 先刪除 TaskNotification
        TaskNotification.objects.filter(
            drive_name=drive_name,
            file_path=file_path,
            host_id=context['user']['id']
        ).delete()
        # 再刪除 TaskManager
        TaskManager.objects.filter(
            drive_name=drive_name,
            file_path=file_path,
            host_id=context['user']['id']
        ).delete()
        return JsonResponse({"status": "ok"})
    return JsonResponse({"error": "Invalid request"}, status=400)