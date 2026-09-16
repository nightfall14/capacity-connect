# Capacity Connect

Capacity Connect is a FastAPI application for managing course capacity, trainer
assignments, trainee bookings, and attendance history. It uses Jinja2,
Bootstrap 5, vanilla JavaScript, SQLite, SQLAlchemy, and native WebSockets.

## Features

- Session authentication with administrator, trainer, and trainee roles.
- Trainer registration with administrator approval.
- Course CRUD, trainer assignment, status changes, and capacity validation.
- Trainee course search, booking, cancellation, profile management, and history.
- Persistent booking history with server-side authorization and overbooking checks.
- Real-time global and private chat for approved trainees and trainers, with
  online presence, persisted history, unread counts, and notifications.
- Course statuses are exactly `Registered`, `In Progress`, and `Completed`.
- Safe startup migration from the original SQLite layout: existing records are
  retained while account, course, role, and booking references are upgraded.

## Setup

```bash
cd trekking_app
pip install -r requirements.txt
python run.py
```

The application listens on `http://127.0.0.1:5001`. The existing
`instance/trekking.db` file is used when present; otherwise a new SQLite
database is created. Existing records are retained and course statuses are
normalized to `Registered`, `In Progress`, or `Completed` on startup.

## Seed credentials

| Role | Email | Password |
| --- | --- | --- |
| Administrator | admin@capacityconnect.com | Admin@123 |
| Trainer | trainer1@capacityconnect.com | Trainer@123 |
| Trainer | trainer2@capacityconnect.com | Trainer@123 |
| Trainer (pending) | trainer3@capacityconnect.com | Trainer@123 |
| Trainee | trainee1@capacityconnect.com | Trainee@123 |
| Trainee | trainee2@capacityconnect.com | Trainee@123 |

Sample courses are created automatically when there are no non-administrator
accounts. Deleting `instance/capacity_connect.db` and restarting recreates sample data.

## Project structure

```text
app/
  models.py              Account, Course, Booking, and chat models
  schemas.py             Pydantic request and WebSocket payload models
  decorators.py          FastAPI authentication helpers
  routes/
    main.py              Public landing page
    auth.py              Registration and login
    admin.py             Administrator management
    trainer.py           Trainer workflows
    trainee.py           Trainee workflows
  templates/             Jinja2 views
  static/                CSS and JavaScript
```

Chat is available to approved trainers and trainees at `/chat`. It uses
`/ws/chat` native WebSockets and persists global and private messages,
presence, unread counts, read markers, and notifications in SQLite.

Set a strong `SECRET_KEY` and change the administrator password before
production deployment. Flask and Flask-SocketIO are no longer required.
