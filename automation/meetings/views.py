from django.shortcuts import render
from core.views import initialize_context
from django.http import HttpResponseRedirect, HttpResponseBadRequest, JsonResponse
from django.urls import reverse
from core.graph_client import get_iana_from_windows
from dateutil import tz, parser
from core.models import UserToken
from core.teams_client import TeamsClient
from core.graph_client import GraphClient
from .models import AutoScheduleMeeting
from django.contrib import messages
from .utils import get_attendee_data, inform_attendees
import uuid
from django import forms
from .tasks import process_meeting_status
from django.views.decorators.http import require_GET
from django.core.serializers.json import DjangoJSONEncoder
from django.utils import timezone
from core.utils import Trie
from django.core.cache import cache

# 新增一個表單類別
class TimeSlotPickForm(forms.Form):
    time_slots = forms.MultipleChoiceField(
        widget=forms.CheckboxSelectMultiple,
        label="請選擇會議時間",
        required=True
    )

def schedule_meeting(request):
    context = initialize_context(request)
    user = context['user']
    time_zone = get_iana_from_windows(user['timeZone'])
    tz_info = tz.gettz(time_zone)
    if not user['is_authenticated']:
        return HttpResponseRedirect(reverse('signin'))
    teams_client = TeamsClient(context['user']['id'])

    # 判斷是否為第二步（選時段）
    if request.method == 'POST' and 'pick_time_slots' in request.POST:
        selected_indexes = request.POST.getlist('time_slots')
        meeting_data = request.session.get('meeting_data')
        time_slots = request.session.get('time_slots')
        if not meeting_data or not time_slots:
            messages.error(request, "Session expired, please re-submit meeting info.")
            return render(request, 'auto_schedule_meeting.html', context)
        # 取出被選中的 slot 資料，並轉換為使用者時區
        def convert_slot_to_user_tz(slot, tz_info):
            import copy
            slot = copy.deepcopy(slot)
            start_utc = parser.isoparse(slot['start'])
            end_utc = parser.isoparse(slot['end'])
            slot['start'] = start_utc.astimezone(tz_info).isoformat()
            slot['end'] = end_utc.astimezone(tz_info).isoformat()
            return slot
        selected_slots = [convert_slot_to_user_tz(time_slots[int(idx)], tz_info) for idx in selected_indexes]
        meeting = AutoScheduleMeeting(**meeting_data)
        meeting.set_candidate_times(selected_slots)
        meeting.status = 'waiting'
        meeting.save()
        inform_attendees(teams_client, meeting)
        process_meeting_status.delay(str(meeting.uuid))  # 非同步啟動
        context['meeting'] = meeting
        # 清理 session
        del request.session['meeting_data']
        del request.session['time_slots']
        return render(request, 'auto_schedule_meeting_progress.html', context)

    if request.method == 'POST':
        start_time = parser.parse(request.POST.get('start_time'))
        end_time = parser.parse(request.POST.get('end_time'))
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=tz_info)
        if end_time.tzinfo is None:
            end_time = end_time.replace(tzinfo=tz_info)
        attendees = request.POST.getlist('attendees')
        attendees_data = get_attendee_data(teams_client, attendees)
        meeting = AutoScheduleMeeting(
            title=request.POST.get('title'),
            description=request.POST.get('description'),
            duration=int(request.POST.get('duration')),
            start_time=start_time,
            end_time=end_time,
            status='pending'
        )
        meeting.set_attendees(attendees_data)
        meeting.host_email = request.session.get("user").get("email")
        meeting.time_zone = time_zone
        try:
            time_slots = teams_client.get_meeting_times_slots(meeting, time_zone)
        except Exception as e:
            messages.error(request, "cannot find available time for meeting for all attendees")
            return render(request, 'tutorial/auto_schedule_meeting.html', context)
        if not time_slots:
            messages.error(request, "cannot find available time for meeting for all attendees")
            return render(request, 'tutorial/auto_schedule_meeting.html', context)
        # 將 meeting 相關資料與 time_slots 暫存於 session
        request.session['meeting_data'] = {
            'title': meeting.title,
            'description': meeting.description,
            'duration': meeting.duration,
            'start_time': meeting.start_time.isoformat(),
            'end_time': meeting.end_time.isoformat(),
            'status': meeting.status,
            'host_email': meeting.host_email,
            'time_zone': meeting.time_zone,
            'attendees': meeting.attendees,
            'attendee_responses': meeting.attendee_responses,
            'current_try': meeting.current_try
        }
        request.session['time_slots'] = time_slots
        # 轉換 slot 時間為使用者時區，並格式化顯示
        from datetime import timezone

        def format_slot_time(slot, tz_info):
            from dateutil import parser
            start_utc = parser.isoparse(slot['start'])
            end_utc = parser.isoparse(slot['end'])
            # 如果沒有 tzinfo，預設為 UTC
            if start_utc.tzinfo is None:
                start_utc = start_utc.replace(tzinfo=timezone.utc)
            if end_utc.tzinfo is None:
                end_utc = end_utc.replace(tzinfo=timezone.utc)
            start_local = start_utc.astimezone(tz_info).strftime('%Y-%m-%d %H:%M')
            end_local = end_utc.astimezone(tz_info).strftime('%Y-%m-%d %H:%M')
            return f"{start_local} ~ {end_local}"
        
        slot_choices = [(str(i), format_slot_time(slot, tz_info)) for i, slot in enumerate(time_slots)]
        form = TimeSlotPickForm()
        form.fields['time_slots'].choices = slot_choices
        context['form'] = form
        return render(request, 'pick_time_slots.html', context)

    return render(request, 'auto_schedule_meeting.html', context)


# 用來處理會議回應的 webhook
def meeting_response(request):
    user_id = request.GET.get('userId')
    uuid_str = request.GET.get('uuid')
    response_status = request.GET.get('response')

    if not user_id or not uuid_str or not response_status:
        return HttpResponseBadRequest("Missing parameters")

    try:
        meeting_uuid = uuid.UUID(uuid_str)
        meeting = AutoScheduleMeeting.objects.get(uuid=meeting_uuid)
    except (ValueError, AutoScheduleMeeting.DoesNotExist):
        return HttpResponseBadRequest("Invalid meeting UUID")

    # 找出對應的 email
    attendees = meeting.get_attendee_responses()
    matched_email = None

    for email, data in attendees.items():
        if data.get('user_id') == user_id:
            matched_email = email
            break

    if not matched_email:
        return HttpResponseBadRequest("Attendee not found for tenant")

    # 更新回應
    meeting.update_attendee_response(matched_email, status=response_status)
    meeting.save()
    process_meeting_status.delay(str(meeting.uuid))  # 觸發 Celery task
    return render(request, 'auto_close.html', {
        'email': matched_email,
        'response': response_status
    })


def meeting_status(request, meeting_uuid):
    teams_client = TeamsClient(request.session.get("user").get("id"))
    try:
        meeting = AutoScheduleMeeting.objects.get(uuid=meeting_uuid)
        # 更新會議狀態邏輯
        if meeting.status == 'waiting':
            response_summary = meeting.get_response_summary()

            # 如果有與會者拒絕，嘗試下一個候選時間
            if response_summary['declined'] > 0:
                try:
                    # declined_attendees = [email for email, response in meeting.get_attendee_responses().items() if response['status'] == 'declined']
                    # declined_list = ', '.join(declined_attendees)
                    # declined_html = ''.join(f"<li>{email}</li>" for email in declined_list)
                    # msg = (
                    #     f"<p><strong>⚠️ A participant has <span style='color:red;'>declined</span> the meeting.</strong></p>"
                    #     f"<p><strong>Declined by:</strong></p>"
                    #     f"<ul>{declined_html}</ul>"
                    #     f"<p><strong>Meeting UUID:</strong> <code>{meeting.uuid}</code></p>"
                    #     f"<p><strong>Declined meeting time:</strong><br>"
                    #     f"<span style='color:#0078D4;'>{meeting.get_candidate_time()['start']} - {meeting.get_candidate_time()['end']}</span></p>"
                    # )
                    # 更新下一段時間並初始化與會者狀態
                    meeting.try_next()
                    # inform_attendees(token, meeting, msg)
                    # 通知與會者
                    inform_attendees(teams_client, meeting)
                except ValueError:
                    # 沒有更多候選時間，標記為失敗
                    meeting.status = 'failed'
                meeting.save()

            # 如果所有人都接受，更新狀態為 'done' 並設置選定時間
            elif response_summary['pending'] == 0 and response_summary['declined'] == 0:
                meeting.status = 'done'
                meeting.selected_time = meeting.get_candidate_time()
                meeting.save()
                # 寄出會議邀請
                attendees_emails = [email for email in meeting.get_attendee_responses().keys()]
                attendees_emails.append(meeting.host_email)
                res = teams_client.create_event(
                    meeting.title,
                    meeting.selected_time["start"],
                    meeting.selected_time["end"],
                    attendees_emails,
                    meeting.description,
                    meeting.time_zone
                )

        # 準備與會者數據
        attendees = []
        for email, response in meeting.get_attendee_responses().items():
            status_class = {
                'pending': 'warning',
                'accepted': 'success',
                'declined': 'danger',
                'tentative': 'info'
            }.get(response['status'], 'secondary')
            
            status_text = {
                'pending': 'Waiting for response',
                'accepted': 'Accepted',
                'declined': 'Declined',
                'tentative': 'Tentative'
            }.get(response['status'], '未知')
            
            attendees.append({
                'email': email,
                'status': response['status'],
                'status_class': status_class,
                'status_text': status_text,
                'response_time': response.get('response_time')
            })
        
        # 準備狀態消息
        status_messages = {
            'pending': 'Initializng...',
            'waiting': 'Waiting...',
            'done': 'Meeting scheduled successfully!',
            'failed': 'Meeting scheduling failed'
        }
        
        status_classes = {
            'pending': 'info',
            'waiting': 'warning',
            'done': 'success',
            'failed': 'danger'
        }
        
        response_data = {
            'status': meeting.status,
            'status_message': status_messages.get(meeting.status, 'unkown status'),
            'status_class': status_classes.get(meeting.status, 'secondary'),
            'attendees': attendees,
            'selected_time': meeting.selected_time if meeting.selected_time else None
        }
        
        return JsonResponse(response_data)
    except AutoScheduleMeeting.DoesNotExist:
        return JsonResponse({'error': 'Meeting not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

def get_contacts(request):
    context = initialize_context(request)
    user = context['user']
    if not user['is_authenticated']:
        return HttpResponseRedirect(reverse('signin'))
    
    trie = cache.get(f"contacts_trie_{user['id']}")
    if trie is None:
        graph_client = GraphClient(context['user']['id'])
        all_contacts = graph_client.get_all_contacts()  # 你要實作這個方法
        trie = Trie()
        for contact in all_contacts:
            trie.insert(contact, contact['email'])  # 或 contact['name']
        cache.set(f"contacts_trie_{user['id']}", trie, timeout=3600)

    query = request.GET.get('query', '')
    if not query:
        return JsonResponse([], safe=False)
    results = trie.search_prefix(query)
    return JsonResponse(results, safe=False)
@require_GET
def list_meetings(request):
    context = initialize_context(request)
    user = context['user']
    user_email = None
    if not user['is_authenticated']:
        return HttpResponseRedirect(reverse('signin'))
    if user['is_authenticated']:
        user_email = user['email']

    if not user_email:
        return JsonResponse({"meetings": []})
    # 這裡可以根據需求過濾（如只顯示自己的、或最近一週的）
    meetings = AutoScheduleMeeting.objects.filter(host_email=user_email).order_by('-created_at')
    data = []
    for m in meetings:
        data.append({
            "uuid": str(m.uuid),
            "title": m.title,
            "status": m.status,
            "created_at": m.created_at.isoformat() if hasattr(m, "created_at") else "",
            "host_email": m.host_email,
        })
    return JsonResponse({"meetings": data})

from django.shortcuts import get_object_or_404

def meeting_progress_view(request, meeting_uuid):
    context = initialize_context(request)
    user = context['user']
    if not user['is_authenticated']:
        return HttpResponseRedirect(reverse('signin'))
    meeting = get_object_or_404(AutoScheduleMeeting, uuid=meeting_uuid)
    # 你可以複用 meeting_status 裡面準備 context 的那段
    attendees = []
    for email, response in meeting.get_attendee_responses().items():
        status_class = {
            'pending': 'warning',
            'accepted': 'success',
            'declined': 'danger',
            'tentative': 'info'
        }.get(response['status'], 'secondary')
        status_text = {
            'pending': 'Waiting for response',
            'accepted': 'Accepted',
            'declined': 'Declined',
            'tentative': 'Tentative'
        }.get(response['status'], '未知')
        attendees.append({
            'email': email,
            'status': response['status'],
            'status_class': status_class,
            'status_text': status_text,
            'response_time': response.get('response_time')
        })

    status_messages = {
        'pending': 'Initializng...',
        'waiting': 'Waiting...',
        'done': 'Meeting scheduled successfully!',
        'failed': 'Meeting scheduling failed'
    }
    status_classes = {
        'pending': 'info',
        'waiting': 'warning',
        'done': 'success',
        'failed': 'danger'
    }
    context = {
        'meeting': meeting,
        'status': meeting.status,
        'status_message': status_messages.get(meeting.status, 'unkown status'),
        'status_class': status_classes.get(meeting.status, 'secondary'),
        'attendees': attendees,
        'selected_time': meeting.selected_time if meeting.selected_time else None
    }
    return render(request, "auto_schedule_meeting_progress.html", context)

from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse

@require_POST
def delete_meeting(request, meeting_uuid):
    try:
        meeting = AutoScheduleMeeting.objects.get(uuid=meeting_uuid)
        # 這裡可以加權限檢查：只能刪除自己的會議
        user = request.session.get("user")
        if not user or meeting.host_email != user.get("email"):
            return JsonResponse({"error": "Permission denied"}, status=403)
        meeting.delete()
        return JsonResponse({"success": True})
    except AutoScheduleMeeting.DoesNotExist:
        return JsonResponse({"error": "Meeting not found"}, status=404)
    

