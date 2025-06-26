from typing import List, Dict, Any
from bs4 import BeautifulSoup
import json

def parse_graph_chat_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Parse chat messages from Microsoft Graph API /chats/messages endpoint,
    extract clean text content and reply-to relationships.

    Args:
        messages (List[Dict]): List of message dicts from Graph API.

    Returns:
        List[Dict]: Each message with id, sender, text, timestamp, and reply_to_id (if available)
    """
    parsed = []

    for msg in messages:
        msg_id = msg.get('id', '')
        if msg.get('from') is None:
            continue
        
        sender = msg.get('from', {}).get('user', {}).get('displayName', 'Unknown')
        html_content = msg.get('body', {}).get('content', '')
        timestamp = msg.get('createdDateTime', '')
        reply_to_id = []

        # 處理 reply-to 訊息關係
        attachments = msg.get('attachments', [])
        for attachment in attachments:
            if attachment.get("contentType") == "messageReference":
                try:
                    # `attachment['content']` 是一個 JSON 字串
                    referenced_msg = json.loads(attachment.get("content", "{}"))
                    if reply_to_id is not None:
                        reply_to_id.append({"msg_id":referenced_msg.get("messageId")
                                            , "sender":referenced_msg.get("messageSender").get('user').get('displayName')
                                            , "msg_preview":referenced_msg.get("messagePreview")})  # <-- 這是原始訊息 ID
                    # 可擴充：也可以抓 preview 或 sender 名字
                except Exception as e:
                    print(f"Error parsing messageReference: {e}")

        # 使用 BeautifulSoup 清除 HTML
        soup = BeautifulSoup(html_content, 'html.parser')
        clean_text = soup.get_text(separator='\n').strip()

        parsed.append({
            "id": msg_id,
            "sender": sender,
            "text": clean_text,
            "timestamp": timestamp,
            "reply_to_id": None if len(reply_to_id)==0 else reply_to_id
        })

    return parsed

def make_prompt_for_unanswered_questions(processed_msgs: List[Dict], max_len=None):
    """
    將處理好的訊息列表製作成給 LLM 的 prompt。
    包含回覆訊息的 sender 與 msg_preview，讓 LLM 更容易判斷是否有回應。

    Args:
        processed_msgs (List[Dict]): 
            每則訊息 dict 包含 keys: "id", "sender", "text", "timestamp",
            選用 key: "reply_to_id" -> list of dicts: [{"msg_id", "sender", "msg_preview"}]

    Returns:
        str: 用於語意分析的 prompt 字串
    """
    # 時間排序
    sorted_msgs = sorted(processed_msgs, key=lambda x: x.get('timestamp', ''))

    dialog_lines = []
    for count, msg in enumerate(sorted_msgs):
        if max_len:
            if count >= max_len:
                break

        time = msg.get('timestamp', '未知時間')
        sender = msg.get('sender', '未知發話者')
        text = msg.get('text', '').replace('\n', ' ')
        # 處理回覆資訊（回覆 preview + sender）
        reply_to_list = msg.get('reply_to_id', [])
        if isinstance(reply_to_list, list) and len(reply_to_list) > 0:
            reply_info = reply_to_list[0]  # 目前僅使用第一個回覆對象
            reply_sender = reply_info.get("sender", "未知對象")
            msg_preview = reply_info.get("msg_preview", "").strip().replace('\n', ' ')
            reply_tag = f"(回覆: {reply_sender}「{msg_preview}」)"
        else:
            reply_tag = ""

        dialog_lines.append(f"{time} - {sender} {reply_tag}: {text}")

    dialog_text = "\n".join(dialog_lines)

    prompt = (
        """
        請你講中文。
        你是一位會議對話分析師，專門從團隊聊天室中找出那些提問但完全沒有人回應的問題。

        請逐步思考每一則訊息，流程如下：
        1. 判斷這則訊息是否為一個問題（即詢問某人某事）。
        2. 如果是問題，再判斷是否有任何人對此訊息進行了回應（無論內容是否完整，只要有「回覆」即視為已回應）。

        ⚠️ 僅當問題**完全沒有任何回應**時，才視為「未回應問題」。
        - 若有其他人稍作回應、表達看法、或僅部分回覆，也算「有回應」。
        - 即使回覆不是直接回答問題，只要有「回應」動作就算。

        如果所有問題都有被回應，請只回覆 `None`。

        若有找到未被回應的問題，請以如下格式列出，**不要包含多餘對話**：
        ---
        問題內容：
        提問者：
        時間：
        為何被視為未回應問題：

        [以下是對話內容]
        """
        f"{dialog_text}\n"
    )
    prompt = prompt.replace('\n',' ').replace('\xa0',' ')
    return  prompt

def analyze_unanswered_questions(raw_chat, model):
    processed_msgs = parse_graph_chat_messages(raw_chat)
    prompt = make_prompt_for_unanswered_questions(processed_msgs)
    # 第一次推理
    first_response = model.generate_content(
        prompt,
        generation_config={
            "temperature": 0,
            "top_p": 0,
            "top_k": 1,
            "max_output_tokens": 1024,
            "stop_sequences": []
        }
    ).text

    print("🔍 初步回應：\n", first_response)

    # 第二次 refine
    refine_prompt = f"""你剛才的回應是：
    {first_response}

    請你幫我做以下精煉：
    - 確保理由中若是使用反向語氣（提及雖然、但是），則刪除整個問題內容
    - 若理由為非完整回應，則刪除整個問題內容
    - 如果格式符合規範且沒錯誤，就原樣輸出
    - 如果你刪光了，請回覆 `None`。

    請直接輸出精煉後的版本，不要補充說明。"""

    refined_response = model.generate_content(
        refine_prompt,
        generation_config={
            "temperature": 0,
            "top_p": 0,
            "top_k": 1
        }
    ).text

    print("✨ 精煉後結果：\n", refined_response)
    return refined_response