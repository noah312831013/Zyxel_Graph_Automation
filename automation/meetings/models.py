from django.db import models
import json
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

# Create your models here.
class AutoScheduleMeeting(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('waiting', 'Waiting'),
        ('done', 'Done'),
        ('failed', 'Failed'),
    ]

    RESPONSE_CHOICES = [
        ('pending', 'Pending'),
        ('accepted', 'Accepted'),
        ('declined', 'Declined'),
        ('tentative', 'Tentative'),
    ]

    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    host_email = models.EmailField(help_text="Email address of the host")
    attendees = models.JSONField(help_text="List of attendee email addresses")
    attendee_responses = models.JSONField(
        default=dict,
        help_text="Dictionary of attendee responses: {email: {'status': status, 'response_time': timestamp, 'user_id': user_id, 'chat_id': chat_id}}"
    )
    candidate_times = models.JSONField(help_text="List of candidate time slots")
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default='pending',
        help_text="Current status of the scheduling process"
    )
    current_try = models.IntegerField(default=0, help_text="Current attempt number")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    title = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)
    duration = models.IntegerField(help_text="Duration in minutes")
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    selected_time = models.JSONField(null=True, blank=True)
    time_zone = models.CharField(max_length=50, default='UTC', help_text="Time zone of the meeting")
    def __str__(self):
        return f"Auto Schedule Meeting {self.id} - {self.status}"

    def set_attendees(self, attendees_data):
        """
        設置與會者列表和他們的 user ID 及 chat ID
        :param attendees_data: 與會者的資料列表，每個元素是包含 'email', 'user_id', 'chat_id' 的字典
        """
        self.attendees = json.dumps([attendee['email'] for attendee in attendees_data])
        
        # 初始化每個與會者的回應狀態
        responses = {}
        for attendee in attendees_data:
            email = attendee['email']
            user_id = attendee.get('user_id')
            chat_id = attendee.get('chat_id')
            responses[email] = {
                'status': 'pending',
                'response_time': None,
                'user_id': user_id,
                'chat_id': chat_id
            }
        self.attendee_responses = json.dumps(responses)

    def get_attendees(self):
        return json.loads(self.attendees)

    def get_attendee_responses(self):
        return json.loads(self.attendee_responses)

    def update_attendee_response(self, email, status, user_id=None, chat_id=None):
        """
        更新與會者的回應狀態
        :param email: 與會者郵箱
        :param status: 回應狀態
        :param user_id: 可選的 user ID
        :param chat_id: 可選的 chat ID
        """
        responses = self.get_attendee_responses()
        if email in responses:
            responses[email].update({
                'status': status,
                'response_time': datetime.now().isoformat()
            })
            if user_id is not None:
                responses[email]['user_id'] = user_id
            if chat_id is not None:
                responses[email]['chat_id'] = chat_id
            self.attendee_responses = json.dumps(responses)
            self.save()

    def get_attendee_status(self, email):
        responses = self.get_attendee_responses()
        return responses.get(email, {}).get('status', 'pending')

    def get_attendee_user_id(self, email):
        responses = self.get_attendee_responses()
        return responses.get(email, {}).get('user_id')

    def get_attendee_chat_id(self, email):
        responses = self.get_attendee_responses()
        return responses.get(email, {}).get('chat_id')

    def get_attendees_by_user(self, user_id):
        """
        獲取特定 user 的所有與會者
        :param user_id: user ID
        :return: 該 user 的與會者郵箱列表
        """
        responses = self.get_attendee_responses()
        return [email for email, data in responses.items() 
                if data.get('user_id') == user_id]

    def set_candidate_times(self, times_list):
        self.candidate_times = json.dumps(times_list)

    def get_candidate_times(self):
        return json.loads(self.candidate_times)

    def get_response_summary(self):
        responses = self.get_attendee_responses()
        summary = {
            'pending': 0,
            'accepted': 0,
            'declined': 0,
            'tentative': 0
        }
        for response in responses.values():
            summary[response['status']] += 1
        return summary

    def get_user_summary(self):
        """
        獲取每個 user 的回應統計
        :return: {user_id: {'pending': 0, 'accepted': 0, 'declined': 0, 'tentative': 0}}
        """
        responses = self.get_attendee_responses()
        user_summary = {}
        
        for response in responses.values():
            user_id = response.get('user_id')
            if user_id not in user_summary:
                user_summary[user_id] = {
                    'pending': 0,
                    'accepted': 0,
                    'declined': 0,
                    'tentative': 0
                }
            user_summary[user_id][response['status']] += 1
            
        return user_summary
    def try_next(self):
        """
        更新當前嘗試次數
        :return: None
        """
        if self.current_try >= len(json.loads(self.candidate_times))-1:
            self.status = 'failed'
            self.save()
            raise ValueError("No more candidate times available.")
        else:
            self.current_try += 1
            responses = self.get_attendee_responses()
            for email in responses:
                responses[email]['status'] = 'pending'
                responses[email]['response_time'] = None
            self.attendee_responses = json.dumps(responses)
    def get_candidate_time(self, tz: str = "Asia/Taipei"):
        candidate_times = self.get_candidate_times()
        if not candidate_times or self.current_try < 0 or self.current_try >= len(candidate_times):
            return None

        raw = candidate_times[self.current_try]

        try:
            start_utc = datetime.fromisoformat(raw["start"])
            end_utc = datetime.fromisoformat(raw["end"])
            local_tz = ZoneInfo(tz)

            return {
                "start": start_utc.astimezone(local_tz).strftime("%Y-%m-%d %H:%M"),
                "end": end_utc.astimezone(local_tz).strftime("%Y-%m-%d %H:%M"),
                "confidence": raw["confidence"],
                "attendeeAvailability": raw["attendeeAvailability"]
            }
        except Exception as e:
            print(f"⚠️ get_candidate_time 時間轉換失敗: {e}")
            return raw  # fallback 回原始格式

    class Meta:
        ordering = ['-created_at']