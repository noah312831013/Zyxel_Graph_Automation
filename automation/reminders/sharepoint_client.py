from core.teams_client import TeamsClient
from urllib.parse import quote
import pandas as pd
from io import BytesIO
from openpyxl.utils import get_column_letter
from .models import TaskNotification, TaskManager
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict

def get_excel_col(col_idx_zero_based):
    """將從0開始的index轉為Excel欄位字母（自動+1）"""
    return get_column_letter(col_idx_zero_based + 1)

class GraphSharePointClient(TeamsClient):
    def __init__(self, user_id, site_name="NebulaP8group", drive_name="ScrumSprints", path="Feature to do list+Q&A/[19.10] Mx Feature_to do list+ Q&A.xlsx"):
        super().__init__(user_id)
        self.path = quote(path)
        self.site_name = site_name
        self.drive_name = drive_name
        self.site_id = self._get_site_id(site_name=site_name)
        self.list_id = self._get_list_id()
        self.drive_id = self._get_drive_id()
        self.notify_interval = None

        # column index for the template sheet
        self.col_tag = {
            "status":3, "task": 4, "owner": 5, "estimate_start_date": 6, "estimate_days": 7, "spent_days": 8, "due_date": 9, "note": 10, "MR_link": 11, "teams_group_name": 12
        }
        self.col_letter = {k:v for k, v in zip(self.col_tag.keys(), map(get_excel_col, self.col_tag.values()))}

    # def _get_site_id(self):
    #     url = f"/sites/{self.domain}:/sites/{self.site_name}"
    #     self.site_id = self._send_request(url).json().get("id")
    #     return self.site_id

    def _get_drive_id(self):
        url = f"/sites/{self._get_site_id(self.site_name)}/drives"
        for drive in self._send_request(url).json()["value"]:
            if drive["name"] == self.drive_name:
                self._drive_id = drive["id"]
                return self._drive_id
        raise Exception(f"Drive {self.drive_name} not found")
    
    def _get_list_id(self, drive_name="ScrumSprints"):
        url = f"/sites/{self._get_site_id(self.site_name)}/lists"
        for lst in self._send_request(url).json()["value"]:
            if lst["displayName"] == drive_name:
                self._list_id = lst.get("id")
                return self._list_id
        raise Exception(f"List with name '{drive_name}' not found")

    # for download file usage
    def _build_drive_url(self):
        return f"/sites/{self.site_id}/drives/{self.drive_id}/root:/{self.path}"

    # for write file usage
    def _build_list_url(self):
        return f"/sites/{self.site_id}/lists/{self.list_id}/drive/root:/{self.path}"
    
    def _build_excel_range_url(self, sheet, address):
        return f"{self._build_list_url()}:/workbook/worksheets('{sheet}')/range(address='{address}')"
    
    # return a dict with sheet name as key and DataFrame as value
    def _download_excel_as_df(self, sheet_name=None, file_type="xlsx"):
        url = f"{self._build_drive_url()}:/content"
        res = self._send_request(url)
        if res.status_code != 200:
            raise Exception(f"Download failed: {res.status_code} {res.text}")
        if file_type in ["xls", "xlsx"]:
            return pd.read_excel(BytesIO(res.content), sheet_name, na_values=[""], keep_default_na=False)
        else:
            raise ValueError("Unsupported file type")

    def _write_cell(self, uuid, values):
        task = TaskNotification.objects.get(uuid=uuid)
        url = self._build_excel_range_url(task.sheet_name, task.field_address)
        payload = {"values": values}
        self._send_request(endpoint=url, method="POST",json=payload)
        print("✅ Updated")
        task.status = TaskNotification.Status.COMPLETED
        task.save()
    
    def _create_notify_item(self, context: dict, reason: str, field: str):
        # Retrieve owner information
        owner_email = context.get("owner")
        user_info = {}
        if not pd.isna(owner_email):
            user_info = self.get_user_info_by_email(owner_email) if owner_email else {}
        # Prepare default values for the notification
        defaults = {
            "host_id": self.me['id'],
            "site_name": self.site_name,
            "drive_name": self.drive_name,
            "file_path": self.path,
            "sheet_name": context["sheet_name"],
            "row": context["row_idx"],
            "task": context["task"],
            "teams_group_name": context["teams_group_name"],
            "teams_group_id": context["teams_group_id"],
            "owner_id": user_info.get("id"),
            "owner_email": user_info.get("mail"),
            "owner_name": user_info.get("displayName"),
            "field_address": field,
            "reason": reason,
        }

        # Check for existing notification item
        try:
            existing_item = TaskNotification.objects.filter(
                site_name=self.site_name,
                drive_name=self.drive_name,
                file_path=self.path,
                sheet_name=context["sheet_name"],
                row=context["row_idx"],
                reason=reason,
                host_id=self.me['id'],
            ).first()

            if existing_item:
                # Update the existing item
                for key, value in defaults.items():
                    setattr(existing_item, key, value)
                existing_item.status = TaskNotification.Status.PENDING
                existing_item.save()
                print(f"🔄 Notification updated for task: {context['task']}, reason: {reason}")
            else:
                # Create a new notification item
                obj = TaskNotification.objects.create(**defaults)
                obj.save()
                print(f"✅ Notification created for task: {context['task']}, reason: {reason}")
        except Exception as e:
            print(f"❌ Failed to create or update notification for task: {context['task']}\n{e}")
    
    def _process_row(self, row, row_idx, sheet_name, teams_group_name, teams_group_id):
        if row_idx == 0:
            # 標題列
            return
        
        task = row.iloc[self.col_tag["task"]]
        if pd.isna(task):
            # 確認有無任務名稱
            return
        
        context = {
            "sheet_name": sheet_name,
            "row_idx": row_idx+2,
            "task": task,
            "owner": row.iloc[self.col_tag["owner"]],
            "teams_group_name": teams_group_name,
            "teams_group_id": teams_group_id,
        }

        if str(row.iloc[self.col_tag["status"]]).lower() == "done" or str(row.iloc[self.col_tag["status"]]).lower() == "n/a" :
            # 如果狀態是完成，或是na，則不需要通知
            return
        
        # owner沒有或是不是email格式 發通知（不用繼續往下檢查其他條件）
        if pd.isna(context["owner"]):
            self._create_notify_item(
                context,
                reason="Owner is missing",
                field=f"{self.col_letter["owner"]}{row_idx}"
            )
            return
        elif "@" not in context["owner"]:
            self._create_notify_item(
                context,
                reason="Owner is not valid email",
                field=f"{self.col_letter["owner"]}{row_idx}"
            )
            return
        
        today = pd.Timestamp.now().normalize()
        def to_dt_safe(val):
            return pd.to_datetime(val, errors='coerce')
        estimate_start_date = row.iloc[self.col_tag["estimate_start_date"]]
        estimate_start_date_dt = to_dt_safe(estimate_start_date)

        if pd.isna(estimate_start_date):
            self._create_notify_item(
                context,
                reason="Estimate start date is missing",
                field=f"{self.col_letter["estimate_start_date"]}{row_idx}"
            )
        elif abs((estimate_start_date_dt - today).days) == 1:
            self._create_notify_item(
                context,
                reason="Estimated start date is within one day of today",
                field=f"{self.col_letter["estimate_start_date"]}{row_idx}"
            )

        due_date = row.iloc[self.col_tag["due_date"]]
        due_date_dt = to_dt_safe(due_date)
        if pd.isna(due_date):
            self._create_notify_item(
                context,
                reason="Due date is missing",
                field=f"{self.col_letter["due_date"]}{row_idx}"
            )
        elif abs((due_date_dt - today).days) == 1:
            self._create_notify_item(
                context,
                reason="Due date is within one day of today",
                field=f"{self.col_letter["due_date"]}{row_idx}"
            )

    def _process_sheet(self, df, sheet_name):
        # 檢查有無 teams_group_name 欄位
        try:
            teams_group_name = df.iloc[0, self.col_tag["teams_group_name"]]
        except Exception as e:
            print(e)
            return
        teams_group_id = self.get_chat_id_by_name(teams_group_name)
        # with ThreadPoolExecutor() as executor:
        #     for row_idx, row in df.iterrows():
        #         executor.submit(self._process_row, row, row_idx, sheet_name, teams_group_name, teams_group_id)
        for row_idx, row in df.iterrows():
            self._process_row(row, row_idx, sheet_name, teams_group_name, teams_group_id)

    def _create_mention_message_payload(self, task: TaskNotification):
        if task.owner_email:
            mention = {
                "id": 0,  # Must match <at id="0"> in content
                "mentionText": task.owner_name,
                "mentioned": {
                    "user": {
                        "id": task.owner_id,
                        "displayName": task.owner_name
                    }
                }
            }
            payload = {
                "body": {
                    "contentType": "html",
                    "content": (
                        f"<div>"
                        f"<p>👋 <at id=\"0\">{task.owner_name}</at>, please reply to this message.</p>"
                        f"<p>💬 <i>(Your reply will be automatically recorded to SharePoint)</i></p>"
                        f"<p>📄 <b>Sheet:</b> {task.sheet_name}</p>"
                        f"<p>📝 <b>Task:</b> {task.task}</p>"
                        f"<p>⚠️ <b>Reason:</b> {task.reason}</p>"
                        f"</div>"
                    )
                },
                "mentions": [mention]
            }
        else:
            payload = {
                "body": {
                    "contentType": "html",
                    "content": (
                        f"<div>"
                        f"<p>📄 <b>Sheet:</b> {task.sheet_name}</p>"
                        f"<p>📝 <b>Task:</b> {task.task}</p>"
                        f"<p>⚠️ <b>Reason:</b> {task.reason}</p>"
                        f"</div>"
                    )
                },
            }
        return payload
    # write task to disk
    def create_notify_items(self, notify_interval, sheet_name="automation_test"):
        self.notify_interval = notify_interval
        # 更新最新資料 
        self.scanAnyMatchMsg()
        # sheet_name=None代表下載所有工作表，前端需要增加一個可以選擇sheet name
        sheets = self._download_excel_as_df(sheet_name=sheet_name)
        # 處理excel檔案中所有的row，並存到task notification
        if sheet_name is not None:
            # 處理單一工作表
            self._process_sheet(sheets, sheet_name)
        else:
            # 處理多個工作表
            for name, df in sheets.items():
                self._process_sheet(df, name)
        # 創建任務，signal給celery，只允許一份excel檔一個通知人，避免反覆提醒
        task,created = TaskManager.objects.update_or_create(
            site_name=self.site_name,
            drive_name=self.drive_name,
            file_path=self.path,
            defaults={
                "host_id": self.me['id'],
                "notify_interval": self.notify_interval
            }
        )
        return task

    def notify(self, task:TaskNotification):
        # 發送 Teams 通知
        payload = self._create_mention_message_payload(
            task
        )
        msg_id = self.send_message_to_chat(task.teams_group_id, payload)
        task.msg_id.append(msg_id)
        task.status = TaskNotification.Status.SENT
        task.save()
    # scan notify items and if matched then update the cell and task status in db
    def scanAnyMatchMsg(self):
        # 1. Load all notification records
        notifications = TaskNotification.objects.filter(
            host_id=self.me['id']
        ).exclude(
            status=TaskNotification.Status.COMPLETED
        )
        if len(notifications) == 0:
            print("No pending notifications found.")
            return

        # 2. Group by chat_id
        chat_groups = defaultdict(list)
        # 將每個 item 的完整資訊加入對應的 chat_groups
        for item in notifications:
            chat_groups[item.teams_group_id].append({
                "uuid": item.uuid,
                "owner_id": item.owner_id,
                "msg_id": item.msg_id,
                "task": item.task
            })

        # 3. Iterate each chat group and fetch messages once
        for chat_id, items in chat_groups.items():
            try:
                messages = self.list_msg_in_chats(chat_id)
            except Exception as e:
                print(f"⚠️ Failed to fetch messages for chat {chat_id}: {e}")
                continue

            # 4. Search for replies matching user_id and msg_id in current chat
            for item in items:
                try:
                    user_id = item['owner_id']
                    for mid in item['msg_id']:
                        content = self._search_message_reference(messages, user_id, mid)
                        if content:
                            self._write_cell(item['uuid'], content)
                            print(f"📝 Replied content written for task {item['task']}")
                            break  # only process first found reply
                except Exception as e:
                    print(f"❌ Error processing task {item['task']}: {e}")