# Microsoft Automation Tool

A Django-based automation platform for Microsoft Teams and SharePoint, featuring scheduled reminders, chat analysis, and seamless integration with Microsoft Graph API.

---

## Features

- **SharePoint Reminder**:  
  Automatically tracks project progress by monitoring SharePoint files. Sends reminders to stakeholders via Teams and updates SharePoint based on replies.

- **Auto Schedule Meeting**:  
  Schedule meetings automatically and track their progress.

- **Unanswered Topic Tracker**:  
  Analyze Teams chat logs to find unanswered questions using LLMs (e.g., Gemini).

- **Celery Integration**:  
  Background tasks for reminders and chat analysis.

---

## Folder Structure

```
automation/
├── core/                # Authentication, Graph API, and core logic
├── meetings/            # Meeting scheduling features
├── reminders/           # SharePoint reminder and notification logic
├── Unanswered_Topic_Tracker/ # Chat analysis utilities
├── static/              # CSS and static files
├── templates/           # Django templates
├── requirements.txt     # Python dependencies
├── docker-compose.yml   # Docker orchestration
├── dockerfile           # Docker build file
└── manage.py
```

---

## Quick Start

### 1. Clone the repository

```sh
git clone <your-repo-url>
cd microsoft_automation_tool
```

### 2. Set up Python environment

```sh
python3 -m venv venv
source venv/bin/activate
pip install -r automation/requirements.txt
```

### 3. Configure OAuth

Edit [`automation/core/oauth_settings.yml`](automation/core/oauth_settings.yml) with your Azure AD app credentials.

### 4. Run Migrations

```sh
python automation/manage.py migrate
```

### 5. Start the Development Server

```sh
python automation/manage.py runserver
```

Visit [http://localhost:8000](http://localhost:8000) in your browser.

---

## Docker Usage

Build and run all services (Django, Celery, Redis, Postgres):

```sh
cd automation
docker-compose up --build
```

---

## Environment Variables

- Configure secrets and environment variables in `.env` or via Docker Compose as needed.

---

## Main Apps

- **core**: Auth, user session, Graph API helpers
- **reminders**: SharePoint file monitoring, Teams notifications
- **meetings**: Meeting scheduling and progress tracking
- **Unanswered_Topic_Tracker**: LLM-based chat analysis

---

## Development Notes

- Ignore sensitive files and local artifacts via `.gitignore`.
- Celery is used for background tasks (reminders, chat analysis).
- See `automation/reminders/sharepoint_client.py` for SharePoint/Teams integration logic.

---

## License

MIT License. See [LICENSE](LICENSE) for details.

---

## Credits

Based on Microsoft Graph API and Django.  
Some code and templates ©