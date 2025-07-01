from django.shortcuts import render
from django import forms
from django.http import HttpResponseRedirect, JsonResponse
from django.urls import reverse
from django.views import View
from core.teams_client import TeamsClient
from core.views import initialize_context
from django_celery_beat.models import IntervalSchedule, PeriodicTask, CrontabSchedule
from .models import CeleryBeatTask_UTT
import json
from urllib.parse import quote
from core.graph_client import GraphClient
from .tasks import run_analysis_task
from django.shortcuts import get_object_or_404
from django.contrib import messages
from django.views.decorators.http import require_http_methods
from django.db import transaction


from django.utils import timezone

def list_tasks(request):
    tasks = CeleryBeatTask_UTT.objects.all()
    data = []
    for t in tasks:
        updated_at_local = timezone.localtime(t.updated_at) if t.updated_at else None
        created_at_local = timezone.localtime(t.created_at) if t.created_at else None
        data.append({
            "id": t.pk,
            "chat_name": t.chat_name,
            "display_path": t.display_path,
            "frequency_minutes": t.frequency_minutes,
            "updated_at": updated_at_local.strftime("%Y-%m-%d %H:%M") if updated_at_local else "no update",
            "created_at": created_at_local.strftime("%Y-%m-%d %H:%M") if created_at_local else "",
        })
    return JsonResponse({"tasks": data})


def schedule_chat_analysis(task: CeleryBeatTask_UTT):
    # 建立或取得 CrontabSchedule
    schedule, _ = CrontabSchedule.objects.get_or_create(
        minute=f"*/{task.frequency_minutes}",
        hour='8-19',
        day_of_week='*',
        day_of_month='*',
        month_of_year='*'
    )

    task_name = f"chat-analysis-{task.chat_id}"

    # 檢查是否已存在同名的 PeriodicTask
    periodic_task = PeriodicTask.objects.filter(name=task_name).first()

    if periodic_task:
        # 🔁 更新原有任務
        periodic_task.crontab = schedule
        periodic_task.args = json.dumps([task.pk])
        periodic_task.task = 'Unanswered_Topic_Tracker.tasks.run_analysis_task'
        periodic_task.enabled = True
        periodic_task.save()
        task.periodic_task = periodic_task # type: ignore
    else:
        # 🆕 新增任務
        periodic_task = PeriodicTask.objects.create(
            crontab=schedule,
            name=task_name,
            task='Unanswered_Topic_Tracker.tasks.run_analysis_task',
            args=json.dumps([task.pk]),
        )
        task.periodic_task = periodic_task # type: ignore

    task.save()
    run_analysis_task.delay(task.pk)  # 立即非同步執行一次


@require_http_methods(["POST"])  # 避免用 GET 誤刪
def delete_task(request, task_id):
    task = get_object_or_404(CeleryBeatTask_UTT, pk=task_id)

    try:
        with transaction.atomic():
            # 刪除對應的週期任務
            if task.periodic_task:
                task.periodic_task.delete()

            # 刪除任務本體
            task.delete()

        return JsonResponse({"status": "deleted", "task_id": task_id})

    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)

class ChatIDForm(forms.Form):
    chat_id = forms.ChoiceField(label="Select your chat room")
    drive_name = forms.ChoiceField(label="SharePoint Drive Name")
    file_path = forms.CharField(label="File Path", max_length=1024)
    frequency_minutes = forms.IntegerField(label="Analysis Interval (minutes)", min_value=1, initial=60)

    def __init__(self, *args, **kwargs):
        chat_ids = kwargs.pop('chat_ids', [])
        drive_names = kwargs.pop('drive_names', [])
        super().__init__(*args, **kwargs)
        self.fields['chat_id'].choices = [(cid['id'], cid['topic']) for cid in chat_ids]
        self.fields["drive_name"].choices = [(dn, dn) for dn in drive_names]
        
        # 加上 Bootstrap class="form-control"
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'form-control'})

class UnansweredTopicView(View):
    template_name = "unanswered_topic_form.html"
    def get(self, request):
        context = initialize_context(request)
        user = context['user']
        if not user['is_authenticated']:
            return HttpResponseRedirect(reverse('signin'))
        teams_client = TeamsClient(context['user']['id'])
        site_name = "NebulaP8group"
        chat_ids = teams_client.get_chats()
        # chat_ids is a list of dicts with keys like 'id', 'topic', etc.
        drive_names = teams_client.list_drive(site_name)
        form = ChatIDForm(chat_ids=chat_ids, drive_names=drive_names)
        context['form'] = form
        return render(request, self.template_name, context)

    def post(self, request):
        context = initialize_context(request)
        user = context['user']
        if not user['is_authenticated']:
            return HttpResponseRedirect(reverse('signin'))
        site_name = "NebulaP8group"
        teams_client = TeamsClient(user['id'])
        chat_ids = teams_client.get_chats()
        drive_names = teams_client.list_drive(site_name)
        form = ChatIDForm(request.POST, chat_ids=chat_ids, drive_names=drive_names)
        if form.is_valid():
            GC = GraphClient(user['id'])
            chat_id = form.cleaned_data['chat_id']
            # Get the selected chat's topic (chat name) from chat_ids
            chat_name = next((c['topic'] for c in chat_ids if c['id'] == chat_id), "")
            user_id = user['id']
            drive_name = form.cleaned_data['drive_name']
            file_path = form.cleaned_data['file_path']
            site_id, drive_id = GC._get_site_and_drive_id(site_name, drive_name)
            sharepoint_path = f"sites/{site_id}/drives/{drive_id}/root:/{quote(file_path)}:/content"
            # schedule_unanswered_topic_task.delay(chat_id, user_id)
            task = CeleryBeatTask_UTT.objects.create(
                chat_id=chat_id,
                chat_name = chat_name,
                host_id=user_id,
                sharepoint_path=sharepoint_path,
                display_path = f"{site_name}/{drive_name}/{file_path}",
                frequency_minutes=form.cleaned_data['frequency_minutes'],
            )
            schedule_chat_analysis(task)
            messages.success(request, f"已成功排程任務，聊天室: {chat_name}，每 {task.frequency_minutes} 分鐘執行一次。")
            return HttpResponseRedirect(reverse('unanswered_topic'))
        context['form'] = form
        return render(request, self.template_name, context)