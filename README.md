# Capacity Connect

Capacity Connect is a FastAPI learning platform for technical capacity building. It provides one trainee learning experience built around the learner dashboard, course catalog, course workspace, and lecture player. The stack is Jinja2, Bootstrap/Tailwind utility styles, vanilla JavaScript, SQLite, SQLAlchemy, and native WebSockets.

## Features

- Role-based session authentication for administrators, trainers, and trainees; trainer registration requires approval.
- A published course catalog and a single enrollment flow. Trainees can browse a course, enroll, and continue from their personal course list.
- Structured courses with modules, lecture videos, and supporting resources.
- Lecture playback with transcripts, timestamped Q&A, video telemetry, and a confusion heatmap.
- Trainee readiness and progress indicators, plus trainer views for course readiness, telemetry, and confusion signals.
- Doubt history and transcript-grounded answers for learner questions.
- Community chat, private chat, online presence, unread counts, and peer-rescue support for approved trainees and trainers.
- Administrator and trainer course-management workflows, including publishing and capacity validation.

The legacy booking-era `/trainee` routes are intentionally absent. `Enrollment` is the canonical learner-to-course record; its existing `bookings` database table is retained for data compatibility.

## Setup

```bash
cd /path/to/capacity_connect
pip install -r requirements.txt
python run.py
```

The application listens on `http://127.0.0.1:5001`. It uses an existing `instance/trekking.db` when available; otherwise it creates `instance/capacity_connect.db`. Startup migrations preserve existing records and normalize legacy account, course, and enrollment data.

## Seed credentials

| Role | Email | Password |
| --- | --- | --- |
| Administrator | admin@capacityconnect.com | Admin@123 |
| Trainer | trainer1@capacityconnect.com | Trainer@123 |
| Trainer | trainer2@capacityconnect.com | Trainer@123 |
| Trainer (pending) | trainer3@capacityconnect.com | Trainer@123 |
| Trainee | trainee1@capacityconnect.com | Trainee@123 |
| Trainee | trainee2@capacityconnect.com | Trainee@123 |

Sample courses are created automatically when there are no non-administrator accounts. Deleting `instance/capacity_connect.db` and restarting recreates sample data.

## Project structure

```text
app/
  models/               Canonical SQLAlchemy models (including Enrollment)
  services/             Readiness, transcript Q&A, video, and chat services
  routes/
    courses.py          Course catalog, enrollment, and learning workspace
    learner.py          Trainee dashboard, my courses, doubts, and profile
    video.py            Lecture Q&A, telemetry, and heatmap APIs
    trainer.py          Trainer authoring, readiness, and analytics
    admin.py            Administrator course and account management
  templates/            Jinja2 views
  static/               CSS and JavaScript
```

Set a strong `SECRET_KEY` and change the administrator password before production deployment.
