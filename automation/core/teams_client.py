from core.graph_client import GraphClient
from bs4 import BeautifulSoup

class TeamsClient(GraphClient):
    """
    TeamsClient is a wrapper around the GraphClient to handle Microsoft Teams specific operations.
    It inherits from GraphClient to utilize its methods for making API calls.
    """
    
    def __init__(self, user_id):
        super().__init__(user_id)
        self._chat_id_cache = {}
    def get_chats(self):
        """
        Retrieve a list of all chats for the current user.
        Returns a list of chat objects.
        """
        endpoint = "me/chats"
        chats = []
        next_link = endpoint

        while next_link:
            response = self._send_request(endpoint=next_link, method="GET")
            if response.status_code != 200:
                raise Exception(f"Failed to get chats: {response.status_code} {response.text}")

            data = response.json()
            chats.extend(data.get("value", []))
            # For pagination, Microsoft Graph returns @odata.nextLink as a full URL.
            next_link = data.get("@odata.nextLink")
            if next_link:
                next_link = next_link.replace(self.base_url, "").lstrip("/")

        return chats
    def send_message_to_chat(self, chat_id, message_payload):
        """
        Send a message to a specific chat.
        """
        endpoint = f"chats/{chat_id}/messages"
        response = self._send_request(endpoint=endpoint, method = "POST", data=message_payload)
        if response.status_code >= 300:
            raise Exception(f"Failed to send message: {response.status_code} {response.text}")
        return response.json()['id']
    # polling 用
    def list_msg_in_chats(self, chat_id):
        """
        List all messages in a chat.
        """
        endpoint = f"me/chats/{chat_id}/messages"
        messages = []
        next_link = endpoint

        while next_link:
            response = self._send_request(endpoint=next_link, method="GET")
            if response.status_code != 200:
                raise Exception(f"Failed to fetch messages: {response.status_code} {response.text}")

            data = response.json()
            messages.extend(data.get("value", []))
            # For pagination, Microsoft Graph returns @odata.nextLink as a full URL.
            next_link = data.get("@odata.nextLink")
            if next_link:
                # Remove the base URL if present, since _send_request expects endpoint only
                next_link = next_link.replace(self.base_url, "").lstrip("/")

        return messages
    # 讀excel上的group name 用來找到特定的 chat ID
    def get_chat_id_by_name(self, chat_name):
        """
        Given a chat name, return the chat ID. Uses caching to avoid redundant API calls.
        """
        endpoint = "me/chats"
        next_link = endpoint

        while next_link:
            response = self._send_request(
                endpoint=next_link,
                params={"$select": "topic,id"},
                method="GET"
            )
            if response.status_code != 200:
                raise Exception(f"Failed to get chats: {response.status_code} {response.text}")

            data = response.json()
            chats = data.get("value", [])
            for chat in chats:
                if chat.get("topic") == chat_name:
                    chat_id = chat.get("id")
                    # Cache the chat ID
                    self._chat_id_cache[chat_name] = chat_id
                    return chat_id

            # For pagination, Microsoft Graph returns @odata.nextLink as a full URL.
            next_link = data.get("@odata.nextLink")
            if next_link:
                next_link = next_link.replace(self.base_url, "").lstrip("/")

        raise Exception(f"Chat with name '{chat_name}' not found")
    def _search_message_reference(self, messages, user_id, msg_id):
        for message in messages:
            attachments = message.get("attachments", [])
            if not attachments:
                continue

            if (
                (user_id == "" or message.get("from", {}).get("user", {}).get("id") == user_id) and
                attachments[0].get("contentType") == "messageReference" and
                attachments[0].get("id") == msg_id
            ):
                soup = BeautifulSoup(message['body']['content'], "html.parser")

                for emoji_tag in soup.find_all("emoji"):
                    if emoji_tag.has_attr("alt"):
                        emoji_tag.replace_with(emoji_tag["alt"])


                text = soup.get_text(separator=' ', strip=True)
                return text

        return None