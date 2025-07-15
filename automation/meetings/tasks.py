# automation/meetings/tasks.py
from celery import shared_task
from .models import AutoScheduleMeeting
from core.teams_client import TeamsClient
from .utils import inform_attendees
from core.models import UserToken
from datetime import timezone
@shared_task
def process_meeting_status(meeting_uuid):
    try:
        meeting = AutoScheduleMeeting.objects.get(uuid=meeting_uuid)
        user_id = UserToken.objects.get(user_email=meeting.host_email).user_id
        teams_client = TeamsClient(user_id)  # 你要根據你的 model 拿 host id/email
        if meeting.status == 'waiting':
            response_summary = meeting.get_response_summary()
            if response_summary['declined'] > 0:
                try:
                    meeting.try_next()
                    inform_attendees(teams_client, meeting)
                except ValueError:
                    meeting.status = 'failed'
                meeting.save()
            elif response_summary['pending'] == 0 and response_summary['declined'] == 0:
                meeting.status = 'done'
                meeting.selected_time = meeting.get_candidate_time(tz=timezone.utc)
                meeting.save()
                attendees_emails = list(meeting.get_attendee_responses().keys())
                attendees_emails.append(meeting.host_email)
                teams_client.create_event(
                    meeting.title,
                    meeting.selected_time["start"],
                    meeting.selected_time["end"],
                    attendees_emails,
                    meeting.description,
                )
    except AutoScheduleMeeting.DoesNotExist:
        pass