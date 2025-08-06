from celery import shared_task
from core.teams_client import TeamsClient
from .models import CeleryBeatTask_UTT
from .utils import UnansweredTopicTrackerUtils
import logging
import pandas as pd
from sentence_transformers import SentenceTransformer, util
logger = logging.getLogger(__name__)
column_mapping = {
    "question": "問題內容",
    "asker": "提問者",
    "timestamp": "時間",
    "reason": "未回應原因"
}

@shared_task
def run_analysis_task(task_id):
    # now = datetime.now()
    
    # # ❗ 避免非工作時段執行：20:00 ~ 08:00
    # if now.hour >= 20 or now.hour < 8:
    #     logger.info(f"⏱️ 跳過非工作時段的任務 task_id={task_id}")
    #     return

    try:
        task = CeleryBeatTask_UTT.objects.get(pk=task_id)
        logger.info(f"⏰ 執行分析任務 task_id={task_id}, chat_id={task.chat_id}")

        # 抓取 Teams 對話
        TC = TeamsClient(task.host_id)
        chat_data = TC.list_msg_in_chats(task.chat_id)
        
        # 分析未回覆問題
        UTTU = UnansweredTopicTrackerUtils()
        question_ls = UTTU.analyze_unanswered_questions(chat_data)

        if not question_ls:
            logger.info(f"📭 沒有未回應問題，仍建立空 Excel task_id={task_id}")
            # TODO: 從 SharePoint 刪除舊報告（視需求）
        if task.result_question_ls!=None:
            model = SentenceTransformer('all-MiniLM-L6-v2')
            # encode all questions
            existing_qs = task.result_question_ls
            all_questions = existing_qs + question_ls
            embeddings = model.encode([q["question"] for q in all_questions], convert_to_tensor=True)

            # keep unique questions based on semantic similarity
            unique_questions = []
            added_indices = set()
            for i in range(len(all_questions)):
                if i in added_indices:
                    continue
                unique_questions.append(all_questions[i])
                for j in range(i + 1, len(all_questions)):
                    if j in added_indices:
                        continue
                    sim = util.pytorch_cos_sim(embeddings[i], embeddings[j]).item()
                    if sim > 0.9:
                        added_indices.add(j)
            question_ls = unique_questions
        task.result_question_ls = question_ls  # type: ignore

        # 建立 DataFrame 並上傳 Excel
        df = pd.DataFrame(question_ls, columns=["question", "asker", "timestamp", "reason"])
        df = df.rename(columns=column_mapping)
        TC.upload_excel_with_data(df, task.sharepoint_path)

        task.save()
        logger.info(f"✅ 任務完成 task_id={task_id}")
    
    except CeleryBeatTask_UTT.DoesNotExist:
        logger.warning(f"⚠️ 任務不存在 task_id={task_id}")
    
    except Exception as e:
        logger.exception(f"❌ 任務失敗 task_id={task_id}: {e}")
        raise

