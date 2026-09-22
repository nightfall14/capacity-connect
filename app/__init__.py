"""
Capacity Connect — Application Factory
=======================================
Creates and configures the FastAPI application.  All routes live in their
respective blueprint modules under app/routes/.
"""

from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import inspect, text
from starlette.middleware.sessions import SessionMiddleware

from app.extensions import Base, SessionLocal, engine
from config import Config

BASE_DIR = os.path.dirname(__file__)
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


# ──────────────────────────────────────────────────────────────────────────────
# Jinja2 url_for helper (FastAPI has no built-in named URL reversal)
# ──────────────────────────────────────────────────────────────────────────────

from urllib.parse import urlencode


def _url_for(endpoint: str, **values) -> str:
    paths: dict[str, str] = {
        "static": "/static",
        "main.index": "/",
        # Auth
        "auth.login": "/auth/login",
        "auth.logout": "/auth/logout",
        "auth.register": "/auth/register/{role}",
        # Admin
        "admin.dashboard": "/admin/dashboard",
        "admin.courses": "/admin/courses",
        "admin.create_course": "/admin/courses/create",
        "admin.edit_course": "/admin/courses/{course_id}/edit",
        "admin.delete_course": "/admin/courses/{course_id}/delete",
        "admin.trainers_list": "/admin/trainers",
        "admin.approve_trainer": "/admin/trainers/{trainer_id}/approve",
        "admin.reject_trainer": "/admin/trainers/{trainer_id}/reject",
        "admin.trainees_list": "/admin/trainees",
        "admin.toggle_active": "/admin/accounts/{account_id}/toggle-active",
        # Trainer
        "trainer.dashboard": "/trainer/dashboard",
        "trainer.readiness": "/trainer/readiness",
        "trainer.create_course": "/trainer/courses/create",
        "trainer.generate_transcript": "/trainer/courses/{course_id}/generate-transcript",
        "trainer.transcript": "/trainer/courses/{course_id}/transcript",
        "trainer.profile": "/trainer/profile",
        "trainer.course_detail": "/trainer/courses/{course_id}",
        "trainer.update_slots": "/trainer/courses/{course_id}/update-slots",
        "trainer.upload_module_item": "/trainer/courses/{course_id}/modules/{module_id}/upload",
        "trainer.transcribe_module_item": "/trainer/modules/{item_id}/transcribe",
        "trainer.update_status": "/trainer/courses/{course_id}/update-status",
        "trainer.participants": "/trainer/courses/{course_id}/participants",
        "trainer.create_quiz": "/trainer/courses/{course_id}/quizzes/create",
        "trainer.quiz_questions": "/trainer/quizzes/{quiz_id}/questions",
        "trainer.create_module": "/trainer/courses/{course_id}/modules/create",
        "trainer.edit_module": "/trainer/courses/{course_id}/modules/{module_id}/edit",
        "trainer.delete_module": "/trainer/courses/{course_id}/modules/{module_id}/delete",
        # Learner
        "learner.dashboard": "/learner/dashboard",
        "learner.my_courses": "/learner/my-courses",
        "learner.profile": "/learner/profile",
        "learner.profile_view": "/profiles/{trainee_id}",
        "learner.take_quiz": "/courses/{course_id}/quizzes/{quiz_id}",
        "learner.course_feedback": "/courses/{course_id}/feedback",
        "readiness.profile": "/readiness",
        "courses.catalog": "/courses",
        "courses.summary": "/courses/{course_id}",
        "courses.learn": "/courses/{course_id}/learn",
        "courses.join": "/courses/{course_id}/join",
        "courses.enroll": "/courses/{course_id}/enroll",
        "video.heatmap": "/api/telemetry/heatmap/{video_id}",
        "video.ask": "/api/lecture/{video_id}/ask",
        "trainer.confusion": "/trainer/confusion/{video_id}",
        "trainer.telemetry": "/trainer/courses/{course_id}/telemetry",
        "learner.doubts": "/learner/doubts",
        # Chat
        "chat.chat_page": "/chat",
        "chat.chat_history": "/chat/history",
        "chat.unread_count": "/chat/unread-count",
        "chat.online_status": "/chat/online",
    }
    path = paths.get(endpoint, "/")
    for key, value in list(values.items()):
        placeholder = "{" + key + "}"
        if placeholder in path:
            path = path.replace(placeholder, str(value))
            values.pop(key)
    if endpoint == "static" and "filename" in values:
        path += "/" + str(values.pop("filename")).lstrip("/")
    if values:
        path += "?" + urlencode(values)
    return path


templates.env.globals["url_for"] = _url_for


# ──────────────────────────────────────────────────────────────────────────────
# Flash & context helpers shared by all route modules
# ──────────────────────────────────────────────────────────────────────────────

def flash(request: Request, message: str, category: str = "info") -> None:
    """Append a flash message to the session."""
    request.session.setdefault("_flashes", []).append((category, message))


def build_context(request: Request, db, **values) -> dict:
    """Build a template context dict with session, account, and flash messages."""
    from app.decorators import current_account
    from app.models import User

    account = current_account(request, db)
    flashes = request.session.pop("_flashes", [])

    def get_flashed_messages(with_categories: bool = False):
        return flashes if with_categories else [msg for _, msg in flashes]

    # Compute unread chat count for chat-eligible roles
    unread_total = 0
    if account and account.role in ("trainee", "trainer"):
        unread_total = _unread_count(db, account)

    values.update(
        request=request,
        session=request.session,
        account=account,
        current_user=account,
        unread_total=unread_total,
        _flashes=flashes,
        get_flashed_messages=get_flashed_messages,
    )
    return values


def render(request: Request, db, template: str, **values):
    """Render a Jinja2 template with the standard context."""
    return templates.TemplateResponse(request, template, build_context(request, db, **values))


def _unread_count(db, account) -> int:
    from app.models import ChatMessage, ChatRoomRead
    from sqlalchemy import select
    from collections import Counter as C

    private_count = (
        db.query(ChatMessage)
        .filter_by(recipient_id=account.id, room_type="private", read_at=None)
        .count()
    )
    marker = (
        db.query(ChatRoomRead)
        .filter_by(account_id=account.id, room_key="global")
        .first()
    )
    q = db.query(ChatMessage).filter_by(room_type="global")
    if marker:
        q = q.filter(ChatMessage.created_at > marker.last_read_at)
    return private_count + q.count()


def dashboard_url(role: str) -> str:
    return {
        "admin": "/admin/dashboard",
        "trainer": "/trainer/dashboard",
        "trainee": "/learner/my-courses",
    }.get(role, "/")


# ──────────────────────────────────────────────────────────────────────────────
# Database migration (legacy column/table renames)
# ──────────────────────────────────────────────────────────────────────────────

def _migrate_database() -> None:
    tables = set(inspect(engine).get_table_names())
    with engine.begin() as conn:
        # Table renames from the trekking-app era
        if "users" in tables and "accounts" not in tables:
            conn.exec_driver_sql('ALTER TABLE "users" RENAME TO "accounts"')
        if "treks" in tables and "courses" not in tables:
            conn.exec_driver_sql('ALTER TABLE "treks" RENAME TO "courses"')

        tables = set(inspect(engine).get_table_names())

        if "courses" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("courses")}
            if "assigned_staff_id" in cols and "assigned_trainer_id" not in cols:
                conn.exec_driver_sql(
                    'ALTER TABLE "courses" RENAME COLUMN "assigned_staff_id" TO "assigned_trainer_id"'
                )

        if "bookings" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("bookings")}
            if "user_id" in cols and "trainee_id" not in cols:
                conn.exec_driver_sql(
                    'ALTER TABLE "bookings" RENAME COLUMN "user_id" TO "trainee_id"'
                )

        if "accounts" in tables:
            conn.execute(text("UPDATE accounts SET role='trainer' WHERE role IN ('staff','trainer')"))
            conn.execute(text("UPDATE accounts SET role='trainee' WHERE role IN ('user','trainee')"))

        if "courses" in tables:
            for old, new in [
                ("Pending", "Registered"), ("Approved", "Registered"),
                ("Open", "In Progress"), ("Started", "In Progress"), ("Closed", "Completed"),
            ]:
                conn.execute(text("UPDATE courses SET status=:new WHERE status=:old"), {"new": new, "old": old})
            conn.execute(text(
                "UPDATE courses SET status='Registered' WHERE status NOT IN "
                "('Registered','In Progress','Completed') OR status IS NULL"
            ))

        # Migrate old "Booked" enrollment status to "Enrolled"
        if "bookings" in tables:
            conn.execute(text("UPDATE bookings SET status='Enrolled' WHERE status='Booked'"))

        if "chat_messages" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("chat_messages")}
            if "is_anonymous" not in cols:
                conn.exec_driver_sql(
                    'ALTER TABLE "chat_messages" ADD COLUMN "is_anonymous" BOOLEAN NOT NULL DEFAULT 0'
                )
        if "doubts" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("doubts")}
            if "is_anonymous" not in cols:
                conn.exec_driver_sql(
                    'ALTER TABLE "doubts" ADD COLUMN "is_anonymous" BOOLEAN NOT NULL DEFAULT 0'
                )
            if "video_timestamp_seconds" not in cols:
                conn.exec_driver_sql(
                    'ALTER TABLE "doubts" ADD COLUMN "video_timestamp_seconds" REAL'
                )

        # ── New LMS columns ────────────────────────────────────────────
        if "accounts" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("accounts")}
            for col, defn in [
                ("designation", "VARCHAR(120)"),
                ("department",  "VARCHAR(120)"),
                ("bio",         "TEXT"),
            ]:
                if col not in cols:
                    conn.exec_driver_sql(
                        f'ALTER TABLE "accounts" ADD COLUMN "{col}" {defn}'
                    )
        if "lecture_videos" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("lecture_videos")}
            for col, defn in [
                ("duration_seconds", "REAL"),
                ("transcript_json", "TEXT"),
                ("transcript_status", "VARCHAR(20) NOT NULL DEFAULT 'pending'"),
                ("trainer_draft_transcript", "TEXT"),
                ("public_transcript", "TEXT"),
                ("is_published", "BOOLEAN NOT NULL DEFAULT 0"),
            ]:
                if col not in cols:
                    conn.exec_driver_sql(
                        f'ALTER TABLE "lecture_videos" ADD COLUMN "{col}" {defn}'
                    )
            conn.execute(text(
                "UPDATE lecture_videos SET public_transcript=transcript_json, "
                "transcript_status='published' "
                "WHERE public_transcript IS NULL AND transcript_json IS NOT NULL "
                "AND transcript_status='completed'"
            ))

        if "competency_profiles" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("competency_profiles")}
            for col in ("work_experience", "interests"):
                if col not in cols:
                    conn.exec_driver_sql(f'ALTER TABLE "competency_profiles" ADD COLUMN "{col}" TEXT')

        if "courses" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("courses")}
            for col, defn in [
                ("category",      "VARCHAR(80)"),
                ("thumbnail_url", "VARCHAR(300)"),
                ("video_url",     "VARCHAR(500)"),
                ("transcript_json", "TEXT"),
                ("transcript_status", "VARCHAR(20) NOT NULL DEFAULT 'pending'"),
                ("trainer_draft_transcript", "TEXT"),
                ("public_transcript", "TEXT"),
                ("is_published", "BOOLEAN NOT NULL DEFAULT 0"),
                ("has_unpublished_changes", "BOOLEAN NOT NULL DEFAULT 1"),
                ("last_published_at", "DATETIME"),
            ]:
                if col not in cols:
                    conn.exec_driver_sql(
                        f'ALTER TABLE "courses" ADD COLUMN "{col}" {defn}'
                    )
            conn.execute(text(
                "UPDATE courses SET public_transcript=transcript_json, "
                "transcript_status='published' "
                "WHERE public_transcript IS NULL AND transcript_json IS NOT NULL "
                "AND transcript_status='completed'"
            ))

        if "modules" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("modules")}
            if "is_published" not in cols:
                conn.exec_driver_sql(
                    'ALTER TABLE "modules" ADD COLUMN "is_published" BOOLEAN NOT NULL DEFAULT 0'
                )

        if "module_items" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("module_items")}
            for col, defn in [
                ("trainer_draft_transcript", "TEXT"),
                ("public_transcript", "TEXT"),
                ("is_published", "BOOLEAN NOT NULL DEFAULT 0"),
            ]:
                if col not in cols:
                    conn.exec_driver_sql(
                        f'ALTER TABLE "module_items" ADD COLUMN "{col}" {defn}'
                    )

        if "bookings" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("bookings")}
            if "progress_pct" not in cols:
                conn.exec_driver_sql(
                    'ALTER TABLE "bookings" ADD COLUMN "progress_pct" REAL NOT NULL DEFAULT 0.0'
                )

        if "telemetry_logs" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("telemetry_logs")}
            for col, defn in [
                ("course_id", "INTEGER"),
                ("video_timestamp", "REAL"),
                ("client_timestamp", "DATETIME"),
            ]:
                if col not in cols:
                    conn.exec_driver_sql(
                        f'ALTER TABLE "telemetry_logs" ADD COLUMN "{col}" {defn}'
                    )


# ──────────────────────────────────────────────────────────────────────────────
# Application Factory
# ──────────────────────────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    # 1. Migrate legacy schema then create any missing tables
    _migrate_database()
    # Import models so metadata is populated before create_all
    import app.models  # noqa: F401
    Base.metadata.create_all(engine)

    # 2. Build the FastAPI instance
    application = FastAPI(title="Capacity Connect", version="3.0")
    application.add_middleware(
        SessionMiddleware,
        secret_key=Config.SECRET_KEY,
        max_age=Config.SESSION_MAX_AGE,
        same_site="lax",
        https_only=os.environ.get("SESSION_HTTPS_ONLY", "").lower() == "true",
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.mount(
        "/static",
        StaticFiles(directory=os.path.join(BASE_DIR, "static")),
        name="static",
    )

    # 3. Error handlers
    @application.exception_handler(404)
    async def not_found(request: Request, exc):
        with SessionLocal() as db:
            response = render(request, db, "errors/404.html")
            response.status_code = 404
            return response

    @application.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        if exc.status_code == 401:
            return RedirectResponse("/auth/login", status_code=303)
        if exc.status_code == 403:
            with SessionLocal() as db:
                response = render(request, db, "errors/403.html")
                response.status_code = 403
                return response
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    # 4. Register route modules
    from app.routes.main import router as main_router
    from app.routes.auth import router as auth_router
    from app.routes.admin import router as admin_router
    from app.routes.trainer import router as trainer_router
    from app.routes.chat import router as chat_router
    from app.routes.chat import chat_ws as chat_websocket
    from app.routes.video import router as video_router
    from app.routes.courses import router as courses_router
    from app.routes.learner import router as learner_router
    from app.routes.api import router as api_router

    application.include_router(main_router)
    application.include_router(auth_router, prefix="/auth")
    application.include_router(admin_router, prefix="/admin")
    application.include_router(trainer_router, prefix="/trainer")
    application.include_router(chat_router, prefix="/chat")
    application.add_api_websocket_route("/ws/chat", chat_websocket, name="global_chat")
    application.include_router(video_router)
    application.include_router(courses_router)
    application.include_router(learner_router)
    application.include_router(api_router)

    return application


# ──────────────────────────────────────────────────────────────────────────────
# Module-level `app` instance (for uvicorn "app:app" style imports)
# ──────────────────────────────────────────────────────────────────────────────
app = create_app()
