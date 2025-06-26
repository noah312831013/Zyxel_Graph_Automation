# from reminders.sharepoint_client import GraphSharePointClient
# from google import generativeai as genai
# from .utils import analyze_unanswered_questions
# GEMINI_API_KEY = ""

# # 設定 API 金鑰
# genai.configure(api_key=GEMINI_API_KEY)

# # 建立模型實例（選擇 gemini-1.5-flash）
# model = genai.GenerativeModel(model_name="gemini-1.5-flash")

# 新增一個celery task
# 這個任務會接受chat_id and user_id and 時間（用來定期執行）
# 先使用GraphSharePointClient(user_id實例化).list_msg_in_chats(chat_id)拿到所有對話後使用analyze_unanswered_questions(msgs)得到output
# 使用GraphSharePointClient如果沒有檔案則創建新的有的話複寫舊的