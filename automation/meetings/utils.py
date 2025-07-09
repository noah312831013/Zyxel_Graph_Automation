from core.teams_client import TeamsClient
import json
from core.auth_helper import AuthHelper
from datetime import timedelta

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .models import AutoScheduleMeeting
    
def get_attendee_data(graph_client: TeamsClient, attendees):
    """
    Fetch user IDs and chat IDs for the given attendees and bind them together.
    Returns a list of dictionaries with 'email', 'user_id', and 'chat_id'.
    """
    if not attendees:
        raise ValueError("Attendees list cannot be empty.")

    try:
        # Fetch user IDs and chat IDs in bulk
        user_ids = [
            graph_client.get_user_info_by_email(email).get('id') 
            for email in attendees
        ]
        chat_ids = graph_client.get_chat_ids(user_ids)

        # Combine attendee data
        attendee_data = [
            {'email': email, 'user_id': user_id, 'chat_id': chat_id}
            for email, user_id, chat_id in zip(attendees, user_ids, chat_ids)
        ]

        return attendee_data
    except KeyError as e:
        raise ValueError(f"Missing expected key in response: {str(e)}")
    except Exception as e:
        raise ValueError(f"Error fetching attendee data: {str(e)}")

def create_card_payload(subject, start_time, end_time, user_id, uuid, base_response_url='http:/localhost/webhook/response/',desc=None):
    start_time = start_time+timedelta(hours=8)
    end_time = end_time+timedelta(hours=8)
    card = {
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": [
            {
                "type": "TextBlock",
                "text": f"📢 會議邀請: {subject}",
                "weight": "Bolder",
                "size": "Medium"
            },
            {
                "type": "TextBlock",
                "text": f"🕒 時間: {start_time.strftime('%Y-%m-%d %H:%M')} ~ {end_time.strftime('%Y-%m-%d %H:%M')}"
            },
        ],
        "actions": [
            {
                "type": "Action.OpenUrl",
                "title": "✅ 參加",
                "url": f"{base_response_url}?userId={user_id}&uuid={str(uuid)}&response=accepted"
            },
            {
                "type": "Action.OpenUrl",
                "title": "❌ 不參加",
                "url": f"{base_response_url}?userId={user_id}&uuid={str(uuid)}&response=declined"
            }
        ]
    }

    card_payload = {
        "body": {
            "contentType": "html",
            "content": desc+'<attachment id=\"1\"></attachment>' if desc else "This message was sent automatically by the Microsoft Automation Tool. <attachment id=\"1\"></attachment>"
        },
        "attachments": [
            {
                "id": "1",
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": json.dumps(card)
            }
        ]
    }

    return card_payload

from dateutil import parser

def inform_attendees(teams_client: TeamsClient, meeting: 'AutoScheduleMeeting'):
    redirect = AuthHelper().settings['redirect']
    attendee_responses = meeting.get_attendee_responses()
    for email, data in attendee_responses.items():
        chat_id = data.get('chat_id')
        user_id = data.get('user_id')

        if chat_id:
            card_payload = create_card_payload(
                subject=meeting.title,
                start_time=parser.isoparse(meeting.get_candidate_time()['start']).astimezone(), # type: ignore
                end_time=parser.isoparse(meeting.get_candidate_time()['end']).astimezone(), # type: ignore
                user_id=user_id,
                uuid = meeting.uuid,
                base_response_url=f"{redirect.replace("/callback","")}/meetings/webhook/response/",
                desc=meeting.description
            )
            try:
                response = teams_client.send_message_to_chat(chat_id, card_payload)
            except Exception as e:
                print(f"[❌] Failed to send card to {email} (chat_id: {chat_id})")
                print(f"Error: {e}")
            else:
                print(f"[✅] Card sent to {email}")
        else:
            print(f"[⚠️] No chat_id for {email}, skipping")