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

def schedule_meeting(request):
    context = initialize_context(request)
    user = context['user']
    if not user['is_authenticated']:
        return HttpResponseRedirect(reverse('signin'))
    teams_client = TeamsClient(context['user']['id'])
    if request.method == 'POST':
        # 獲取時區信息
        time_zone = get_iana_from_windows(user['timeZone'])
        tz_info = tz.gettz(time_zone)
        
        # 解析並添加時區信息到日期時間
        start_time = parser.parse(request.POST.get('start_time'))
        end_time = parser.parse(request.POST.get('end_time'))
        
        # 如果日期時間沒有時區信息，添加用戶的時區
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=tz_info)
        if end_time.tzinfo is None:
            end_time = end_time.replace(tzinfo=tz_info)


        # 獲取與會者信息
        attendees = request.POST.getlist('attendees')
        attendees_data = get_attendee_data(teams_client, attendees)

        # 創建新的排程記錄
        meeting = AutoScheduleMeeting(
            title=request.POST.get('title'),
            description=request.POST.get('description'),
            duration=int(request.POST.get('duration')),
            start_time=start_time,
            end_time=end_time,
            status='pending'
        )
        
        # 設置與會者
        meeting.set_attendees(attendees_data)
        meeting.host_email = request.session.get("user").get("email")
        meeting.time_zone = time_zone

        # 嘗試獲取候選時間
        try:
            time_slots = teams_client.get_meeting_times_slots(meeting, time_zone)
        except Exception as e:
            messages.error(request, "cannot find available time for meeting for all attendees")
            return render(request, 'tutorial/auto_schedule_meeting.html', context)

        if not time_slots:
            messages.error(request, "cannot find available time for meeting for all attendees")
            return render(request, 'tutorial/auto_schedule_meeting.html', context)
        
        # 設定候選時間並儲存
        meeting.set_candidate_times(time_slots)
        meeting.status = 'waiting'
        meeting.save()

        inform_attendees(token, meeting)
        context['meeting'] = meeting
        return render(request, 'auto_schedule_meeting_progress.html', context)

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
    
    graph_client = GraphClient(context['user']['id'])
    query = request.GET.get('query','')  # 確保獲取 query 參數

    # 檢查 query 是否為空，若是空則返回錯誤訊息
    if not query:
        return
    contacts = graph_client.search_email(query=query)
    return JsonResponse(contacts, safe=False)