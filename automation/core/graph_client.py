import requests
import base64
import json
from django.utils.dateparse import parse_datetime
from io import BytesIO
import pandas as pd
from typing import TYPE_CHECKING, List, Dict, Any
if TYPE_CHECKING:
    from meetings.models import AutoScheduleMeeting
GRAPH_URL = 'https://graph.microsoft.com/v1.0'
from core.models import UserToken
from urllib.parse import quote

class GraphClient:
    def __init__(self, user_id):
        """
        Initialize the GraphManager with an access token.
        """
        self.base_url = GRAPH_URL
        self.user_id = user_id
        self.me = self.get_user_info()
        self.domain = "unizyx.sharepoint.com"

    def _send_request(self, endpoint, method='GET', params=None, data=None, json=None):
        """
        A generic method to send requests to Microsoft Graph API.
        """
        try:
            user = UserToken.objects.filter(user_id=self.user_id).first()
        except Exception as e:
            print(e)
            user = None
        if not user:
            raise ValueError(f"UserToken not found for user_id: {self.user_id}")
        url = f'{self.base_url}/{endpoint}'
        headers = {
            'Authorization': f'Bearer {user.get_token()}',
            'Content-Type': 'application/json'
        }
        response = requests.request(
            method=method,
            url=url,
            headers=headers,
            params=params,
            json=json,
            data=data
        )
        # 檢查響應狀態碼
        if response.status_code not in (200, 201):
            print(f"⚠️ HTTP Error {response.status_code}: {response.text}")
            response.raise_for_status()

        # 檢查是否為空響應
        if not response.text.strip():
            raise ValueError("Empty response received from server.")
        
        return response
        # # 嘗試解析 JSON
        # try:
        #     return response.json()
        # except json.JSONDecodeError as e:
        #     print(f"⚠️ Failed to decode JSON: {response.text}")
        #     raise

    def get_user_info(self):
        """
        Fetch user information and avatar from Microsoft Graph API.
        """
        # Fetch user information
        user_info = self._send_request(
            endpoint='me',
            params={
                '$select': 'displayName,mail,mailboxSettings,userPrincipalName,id'
            }
        )
        user_info = user_info.json()
        user = UserToken.objects.filter(user_id=self.user_id).first()
        if not user:
            raise ValueError(f"UserToken not found for user_id: {self.user_id}")
        graph_endpoint = f'{self.base_url}/me/photo/$value'
        headers = {
            'Authorization': f'Bearer {user.get_token()}'
        }

        response = requests.get(graph_endpoint, headers=headers)
        user_info['avatar'] = base64.b64encode(response.content).decode('utf-8')

        return user_info

    def get_user_info_by_email(self, email):
        """
        Fetch user information by email.
        """
        endpoint = f'users/{email}'
        user_info = self._send_request(
            endpoint=endpoint,
            # params={
            #     '$select': 'displayName,mail,mailboxSettings,userPrincipalName,id'
            # }
        )
        return user_info.json()

    def get_all_chats(self):
        """
        Fetch all chats for the authenticated user.
        """
        chats = []
        url = 'me/chats'
        
        while url:
            data = self._send_request(endpoint=url).json()
            chats.extend(data.get('value', []))
            url = data.get('@odata.nextLink', None)

        return chats

    def get_chat_ids(self, user_ids):
        """
        Fetch chat IDs for one-on-one chats with the authenticated user.
        """
        if not user_ids:
            raise ValueError("User IDs list cannot be empty.")

        try:
            chats = self.get_all_chats()
            if not chats:
                raise Exception("No chats found for the authenticated user.")

            chat_ids = []
            for user_id in user_ids:
                matched_chat_id = next(
                    (
                        chat.get("id")
                        for chat in chats
                        if chat.get("chatType") == "oneOnOne" and any(
                            member.get("userId") == user_id
                            for member in self._send_request(
                                endpoint=f'chats/{chat.get("id")}/members'
                            ).json().get("value", [])
                        )
                    ),
                    None
                )
                chat_ids.append(matched_chat_id)

            return chat_ids
        except Exception as e:
            raise ValueError(f"Error fetching chat IDs: {str(e)}")
    
    def get_meeting_times_slots(self, meeting: 'AutoScheduleMeeting', timezone: str = 'UTC') -> List[Dict[str, Any]]:
        """
        Fetch available meeting time slots using Microsoft Graph API.
        :param meeting: An instance of AutoScheduleMeeting containing meeting details.
        :param timezone: The timezone to use for the meeting times.
        :return: A list of dictionaries containing meeting time suggestions.
        """
        attendees_list = json.loads(meeting.attendees)  # Convert JSON string to list
        attendees_list.append(meeting.host_email)

        body = {
            "attendees": [
                {
                    "emailAddress": {"address": email},
                    "type": "Required"
                } for email in attendees_list
            ],
            "timeConstraint": {
                "timeslots": [
                    {
                        "start": {
                            "dateTime": meeting.start_time.replace(tzinfo=None).isoformat(),
                            "timeZone": timezone
                        },
                        "end": {
                            "dateTime": meeting.end_time.replace(tzinfo=None).isoformat(),
                            "timeZone": timezone
                        }
                    }
                ]
            },
            "meetingDuration": f"PT{meeting.duration}M"
        }

        try:
            response = self._send_request(
                endpoint='me/findMeetingTimes',
                method='POST',
                json=body
            )
        except requests.exceptions.RequestException as e:
            raise Exception(f"Microsoft Graph API Error: {str(e)}")
        response = response.json()
        # Check if there are no available time slots
        if not response.get("meetingTimeSuggestions"):
            raise Exception("No available meeting time slots found in the response.")

        meeting_times = []
        for suggestion in response.get("meetingTimeSuggestions", []):
            slot = suggestion["meetingTimeSlot"]
            start_dt_raw = parse_datetime(slot["start"]["dateTime"])
            end_dt_raw = parse_datetime(slot["end"]["dateTime"])
            if start_dt_raw:
                start_dt = start_dt_raw.isoformat()
            else:
                raise ValueError(f"Invalid start datetime format: {slot['start']['dateTime']}")
            if end_dt_raw:
                end_dt = end_dt_raw.isoformat()
            else:
                raise ValueError(f"Invalid end datetime format: {slot['end']['dateTime']}")
            meeting_times.append({
                "confidence": suggestion["confidence"],
                "attendeeAvailability": suggestion["attendeeAvailability"],
                "start": start_dt,
                "end": end_dt
            })

        return meeting_times
    
    def create_event(self, subject, start, end, attendees=None, body=None, timezone='UTC'):
        """
        Create a calendar event using Microsoft Graph API.
        """
        new_event = {
            'subject': subject,
            'start': {
                'dateTime': start,
                'timeZone': timezone
            },
            'end': {
                'dateTime': end,
                'timeZone': timezone
            },
            'location': {
                'displayName': "Teams 線上會議",
            },
            'isOnlineMeeting': True,
            'onlineMeetingProvider': "teamsForBusiness",
        }

        if attendees:
            attendee_list = []
            for email in attendees:
                attendee_list.append({
                    'type': 'required',
                    'emailAddress': {'address': email}
                })
            new_event['attendees'] = attendee_list

        if body:
            new_event['body'] = {
                'contentType': 'text',
                'content': body
            }

        response = self._send_request(
            endpoint='me/events',
            method='POST',
            json=new_event
        )
        return response.json()
    def search_email(self, query=None):
        if not query:
            return []
        query = query.strip()
        if not query:
            raise ValueError("Query parameter is required")

        filter_query = f"startswith(displayName,'{query}') or startswith(mail,'{query}')"
        endpoint = f"users"
        params = {
            "$filter": filter_query,
            "$select": "displayName,mail,userPrincipalName"
        }

        try:
            data = self._send_request(endpoint=endpoint, params=params).json()
            if "value" not in data:
                raise ValueError("Invalid response from Graph API")
            data = data.json()
            contacts = []
            for user in data["value"]:
                email = user.get("mail") or user.get("userPrincipalName")
                if email:
                    contacts.append({
                        "name": user.get("displayName", ""),
                        "email": email
                    })

            return contacts

        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Graph API request failed: {e}")
    def list_drive(self,site_name="NebulaP8group"):
        url = f"/sites/{self._get_site_id(site_name)}/drives"
        dn_ls = [drive['name'] for drive in self._send_request(url).json()["value"]]
        return dn_ls
    def _get_site_id(self, site_name):
        url = f"/sites/{self.domain}:/sites/{site_name}"
        self.site_id = self._send_request(url).json().get("id")
        return self.site_id
    def _get_site_and_drive_id(self, site_name, drive_name):
        site_id = self._get_site_id(site_name)
        url = f"/sites/{site_id}/drives"
        for drive in self._send_request(url).json()["value"]:
            if drive["name"] == drive_name:
                drive_id = drive["id"]
                return site_id ,drive_id
        raise Exception(f"Drive {drive_name} not found")
    def upload_excel_with_data(self, df, url):
        # 將 DataFrame 儲存成 Excel 檔（in memory）
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Sheet1')
        output.seek(0)

        # 使用 Graph API PUT 上傳 Excel
        # url = f"sites/{site_id}/drives/{drive_id}/root:/{quote(file_path)}:/content"
        response = self._send_request(url, "PUT", data=output.read())
        response.raise_for_status()
        return response.json()  # 含有 webUrl / id 等資訊


zone_mappings = {
    'Dateline Standard Time': 'Etc/GMT+12',
    'UTC-11': 'Etc/GMT+11',
    'Aleutian Standard Time': 'America/Adak',
    'Hawaiian Standard Time': 'Pacific/Honolulu',
    'Marquesas Standard Time': 'Pacific/Marquesas',
    'Alaskan Standard Time': 'America/Anchorage',
    'UTC-09': 'Etc/GMT+9',
    'Pacific Standard Time (Mexico)': 'America/Tijuana',
    'UTC-08': 'Etc/GMT+8',
    'Pacific Standard Time': 'America/Los_Angeles',
    'US Mountain Standard Time': 'America/Phoenix',
    'Mountain Standard Time (Mexico)': 'America/Chihuahua',
    'Mountain Standard Time': 'America/Denver',
    'Central America Standard Time': 'America/Guatemala',
    'Central Standard Time': 'America/Chicago',
    'Easter Island Standard Time': 'Pacific/Easter',
    'Central Standard Time (Mexico)': 'America/Mexico_City',
    'Canada Central Standard Time': 'America/Regina',
    'SA Pacific Standard Time': 'America/Bogota',
    'Eastern Standard Time (Mexico)': 'America/Cancun',
    'Eastern Standard Time': 'America/New_York',
    'Haiti Standard Time': 'America/Port-au-Prince',
    'Cuba Standard Time': 'America/Havana',
    'US Eastern Standard Time': 'America/Indianapolis',
    'Turks And Caicos Standard Time': 'America/Grand_Turk',
    'Paraguay Standard Time': 'America/Asuncion',
    'Atlantic Standard Time': 'America/Halifax',
    'Venezuela Standard Time': 'America/Caracas',
    'Central Brazilian Standard Time': 'America/Cuiaba',
    'SA Western Standard Time': 'America/La_Paz',
    'Pacific SA Standard Time': 'America/Santiago',
    'Newfoundland Standard Time': 'America/St_Johns',
    'Tocantins Standard Time': 'America/Araguaina',
    'E. South America Standard Time': 'America/Sao_Paulo',
    'SA Eastern Standard Time': 'America/Cayenne',
    'Argentina Standard Time': 'America/Buenos_Aires',
    'Greenland Standard Time': 'America/Godthab',
    'Montevideo Standard Time': 'America/Montevideo',
    'Magallanes Standard Time': 'America/Punta_Arenas',
    'Saint Pierre Standard Time': 'America/Miquelon',
    'Bahia Standard Time': 'America/Bahia',
    'UTC-02': 'Etc/GMT+2',
    'Azores Standard Time': 'Atlantic/Azores',
    'Cape Verde Standard Time': 'Atlantic/Cape_Verde',
    'UTC': 'Etc/GMT',
    'GMT Standard Time': 'Europe/London',
    'Greenwich Standard Time': 'Atlantic/Reykjavik',
    'Sao Tome Standard Time': 'Africa/Sao_Tome',
    'Morocco Standard Time': 'Africa/Casablanca',
    'W. Europe Standard Time': 'Europe/Berlin',
    'Central Europe Standard Time': 'Europe/Budapest',
    'Romance Standard Time': 'Europe/Paris',
    'Central European Standard Time': 'Europe/Warsaw',
    'W. Central Africa Standard Time': 'Africa/Lagos',
    'Jordan Standard Time': 'Asia/Amman',
    'GTB Standard Time': 'Europe/Bucharest',
    'Middle East Standard Time': 'Asia/Beirut',
    'Egypt Standard Time': 'Africa/Cairo',
    'E. Europe Standard Time': 'Europe/Chisinau',
    'Syria Standard Time': 'Asia/Damascus',
    'West Bank Standard Time': 'Asia/Hebron',
    'South Africa Standard Time': 'Africa/Johannesburg',
    'FLE Standard Time': 'Europe/Kiev',
    'Israel Standard Time': 'Asia/Jerusalem',
    'Kaliningrad Standard Time': 'Europe/Kaliningrad',
    'Sudan Standard Time': 'Africa/Khartoum',
    'Libya Standard Time': 'Africa/Tripoli',
    'Namibia Standard Time': 'Africa/Windhoek',
    'Arabic Standard Time': 'Asia/Baghdad',
    'Turkey Standard Time': 'Europe/Istanbul',
    'Arab Standard Time': 'Asia/Riyadh',
    'Belarus Standard Time': 'Europe/Minsk',
    'Russian Standard Time': 'Europe/Moscow',
    'E. Africa Standard Time': 'Africa/Nairobi',
    'Iran Standard Time': 'Asia/Tehran',
    'Arabian Standard Time': 'Asia/Dubai',
    'Astrakhan Standard Time': 'Europe/Astrakhan',
    'Azerbaijan Standard Time': 'Asia/Baku',
    'Russia Time Zone 3': 'Europe/Samara',
    'Mauritius Standard Time': 'Indian/Mauritius',
    'Saratov Standard Time': 'Europe/Saratov',
    'Georgian Standard Time': 'Asia/Tbilisi',
    'Volgograd Standard Time': 'Europe/Volgograd',
    'Caucasus Standard Time': 'Asia/Yerevan',
    'Afghanistan Standard Time': 'Asia/Kabul',
    'West Asia Standard Time': 'Asia/Tashkent',
    'Ekaterinburg Standard Time': 'Asia/Yekaterinburg',
    'Pakistan Standard Time': 'Asia/Karachi',
    'Qyzylorda Standard Time': 'Asia/Qyzylorda',
    'India Standard Time': 'Asia/Calcutta',
    'Sri Lanka Standard Time': 'Asia/Colombo',
    'Nepal Standard Time': 'Asia/Katmandu',
    'Central Asia Standard Time': 'Asia/Almaty',
    'Bangladesh Standard Time': 'Asia/Dhaka',
    'Omsk Standard Time': 'Asia/Omsk',
    'Myanmar Standard Time': 'Asia/Rangoon',
    'SE Asia Standard Time': 'Asia/Bangkok',
    'Altai Standard Time': 'Asia/Barnaul',
    'W. Mongolia Standard Time': 'Asia/Hovd',
    'North Asia Standard Time': 'Asia/Krasnoyarsk',
    'N. Central Asia Standard Time': 'Asia/Novosibirsk',
    'Tomsk Standard Time': 'Asia/Tomsk',
    'China Standard Time': 'Asia/Shanghai',
    'North Asia East Standard Time': 'Asia/Irkutsk',
    'Singapore Standard Time': 'Asia/Singapore',
    'W. Australia Standard Time': 'Australia/Perth',
    'Taipei Standard Time': 'Asia/Taipei',
    'Ulaanbaatar Standard Time': 'Asia/Ulaanbaatar',
    'Aus Central W. Standard Time': 'Australia/Eucla',
    'Transbaikal Standard Time': 'Asia/Chita',
    'Tokyo Standard Time': 'Asia/Tokyo',
    'North Korea Standard Time': 'Asia/Pyongyang',
    'Korea Standard Time': 'Asia/Seoul',
    'Yakutsk Standard Time': 'Asia/Yakutsk',
    'Cen. Australia Standard Time': 'Australia/Adelaide',
    'AUS Central Standard Time': 'Australia/Darwin',
    'E. Australia Standard Time': 'Australia/Brisbane',
    'AUS Eastern Standard Time': 'Australia/Sydney',
    'West Pacific Standard Time': 'Pacific/Port_Moresby',
    'Tasmania Standard Time': 'Australia/Hobart',
    'Vladivostok Standard Time': 'Asia/Vladivostok',
    'Lord Howe Standard Time': 'Australia/Lord_Howe',
    'Bougainville Standard Time': 'Pacific/Bougainville',
    'Russia Time Zone 10': 'Asia/Srednekolymsk',
    'Magadan Standard Time': 'Asia/Magadan',
    'Norfolk Standard Time': 'Pacific/Norfolk',
    'Sakhalin Standard Time': 'Asia/Sakhalin',
    'Central Pacific Standard Time': 'Pacific/Guadalcanal',
    'Russia Time Zone 11': 'Asia/Kamchatka',
    'New Zealand Standard Time': 'Pacific/Auckland',
    'UTC+12': 'Etc/GMT-12',
    'Fiji Standard Time': 'Pacific/Fiji',
    'Chatham Islands Standard Time': 'Pacific/Chatham',
    'UTC+13': 'Etc/GMT-13',
    'Tonga Standard Time': 'Pacific/Tongatapu',
    'Samoa Standard Time': 'Pacific/Apia',
    'Line Islands Standard Time': 'Pacific/Kiritimati'
}

def get_iana_from_windows(windows_tz_name):
    if windows_tz_name in zone_mappings:
        return zone_mappings[windows_tz_name]

    # Assume if not found value is
    # already an IANA name
    return windows_tz_name