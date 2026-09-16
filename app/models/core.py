"""
Capacity Connect — Core SQLAlchemy Models
==========================================
All LMS domain models live here.  Roles:
  • trainee  — learner who enrolls in courses
  • trainer  — instructor who creates/manages courses
  • admin    — platform administrator

Models
------
User (replaces Account), Course, Module, LectureVideo, Enrollment (replaces Booking),
Assessment, Doubt, TelemetryLog, CompetencyProfile,
plus ChatMessage & ChatRoomRead kept for the real-time chat feature.
"""

from __future__ import annotations

from datetime import date, datetime
import hashlib
import hmac
import secrets
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, synonym

from app.extensions import Base


# ──────────────────────────────────────────────────────────────────────────────
# Password helpers (scrypt with pbkdf2 read-back compatibility)
# ──────────────────────────────────────────────────────────────────────────────

def _hash_password(password: str) -> str:
    salt = secrets.token_hex(8)
    digest = hashlib.scrypt(
        password.encode(), salt=salt.encode(), n=32768, r=8, p=1, dklen=64,
        maxmem=128 * 1024 * 1024,
    ).hex()
    return f"scrypt:32768:8:1${salt}${digest}"


def _check_password(password: str, encoded: str) -> bool:
    try:
        method, salt, expected = encoded.split("$", 2)
        if method.startswith("scrypt:"):
            _, n, r, p = method.split(":")
            actual = hashlib.scrypt(
                password.encode(), salt=salt.encode(),
                n=int(n), r=int(r), p=int(p), dklen=64,
                maxmem=128 * 1024 * 1024,
            ).hex()
        elif method.startswith("pbkdf2:"):
            _, algorithm, iterations = method.split(":")
            actual = hashlib.pbkdf2_hmac(
                algorithm, password.encode(), salt.encode(), int(iterations), dklen=32
            ).hex()
        else:
            return False
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


# ──────────────────────────────────────────────────────────────────────────────
# User  (table: accounts — preserves existing data)
# ──────────────────────────────────────────────────────────────────────────────

class User(Base):
    """Platform user.  role ∈ {'trainee', 'trainer', 'admin'}."""

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(150), unique=True, index=True)
    phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="trainee")  # trainee | trainer | admin
    is_approved: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Profile extras (LMS-specific)
    designation: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    department: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    bio: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    enrollments: Mapped[list["Enrollment"]] = relationship(
        back_populates="learner", foreign_keys="Enrollment.user_id",
        cascade="all, delete-orphan",
    )
    assigned_courses: Mapped[list["Course"]] = relationship(
        back_populates="trainer", foreign_keys="Course.trainer_id",
    )
    competency_profile: Mapped[Optional["CompetencyProfile"]] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan",
    )
    assessments_taken: Mapped[list["Assessment"]] = relationship(
        back_populates="learner", foreign_keys="Assessment.learner_id",
        cascade="all, delete-orphan",
    )
    doubts_asked: Mapped[list["Doubt"]] = relationship(
        back_populates="learner", foreign_keys="Doubt.learner_id",
        cascade="all, delete-orphan",
    )
    telemetry_logs: Mapped[list["TelemetryLog"]] = relationship(
        back_populates="user", cascade="all, delete-orphan",
    )

    # Password management
    def set_password(self, password: str) -> None:
        self.password_hash = _hash_password(password)

    def check_password(self, password: str) -> bool:
        return _check_password(password, self.password_hash)

    # Convenience properties
    @property
    def is_trainer_pending(self) -> bool:
        return self.role == "trainer" and not self.is_approved

    @property
    def is_authenticated(self) -> bool:
        return bool(self.is_active)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "email": self.email,
            "phone": self.phone, "role": self.role,
            "is_approved": self.is_approved, "is_active": self.is_active,
            "designation": self.designation, "department": self.department,
        }


# ──────────────────────────────────────────────────────────────────────────────
# Course  (table: courses — preserves existing data)
# ──────────────────────────────────────────────────────────────────────────────

class Course(Base):
    """A training course offered on the platform."""

    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(150), name="name")
    # The database still contains the historical column name; the public model
    # API is now LMS-oriented.
    name = synonym("title")
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Legacy trekking fields kept for DB compatibility
    location: Mapped[str] = mapped_column(String(150), default="Online")
    difficulty: Mapped[str] = mapped_column(String(20), default="Moderate")
    duration: Mapped[str] = mapped_column(String(50), default="Self-paced")
    # LMS-specific
    category: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    thumbnail_url: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    video_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    transcript_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    transcript_status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False
    )
    trainer_draft_transcript: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    public_transcript: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    has_unpublished_changes: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_published_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    total_slots: Mapped[int] = mapped_column(Integer, default=0)
    available_slots: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="In Progress", nullable=False)
    start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    trainer_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("accounts.id"), nullable=True,
        name="assigned_trainer_id",          # preserves existing column name
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    trainer: Mapped[Optional["User"]] = relationship(
        back_populates="assigned_courses", foreign_keys=[trainer_id],
    )
    modules: Mapped[list["Module"]] = relationship(
        back_populates="course", cascade="all, delete-orphan", order_by="Module.order",
    )
    enrollments: Mapped[list["Enrollment"]] = relationship(
        back_populates="course", cascade="all, delete-orphan",
    )
    assessments: Mapped[list["Assessment"]] = relationship(
        back_populates="course", cascade="all, delete-orphan",
    )
    doubts: Mapped[list["Doubt"]] = relationship(
        back_populates="course", cascade="all, delete-orphan",
    )

    def active_enrollments_count(self) -> int:
        return sum(
            1 for e in self.enrollments
            if str(e.status).lower() in {"active", "enrolled", "in progress"}
        )

    # ── Backward-compat aliases ───────────────────────────────────────
    def active_bookings_count(self) -> int:
        return self.active_enrollments_count()

    @property
    def assigned_trainer(self):
        """Alias for trainer — keeps old templates/code working."""
        return self.trainer

    @assigned_trainer.setter
    def assigned_trainer(self, value):
        self.trainer = value

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "location": self.location,
            "difficulty": self.difficulty, "duration": self.duration,
            "total_slots": self.total_slots, "available_slots": self.available_slots,
            "status": self.status,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "trainer": self.trainer.name if self.trainer else None,
        }


# ──────────────────────────────────────────────────────────────────────────────
# Module  (table: modules)
# ──────────────────────────────────────────────────────────────────────────────

class Module(Base):
    """An ordered section within a Course (e.g. Week 1 — Introduction)."""

    __tablename__ = "modules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    order: Mapped[int] = mapped_column(Integer, default=0)
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    course: Mapped["Course"] = relationship(back_populates="modules")
    videos: Mapped[list["LectureVideo"]] = relationship(
        back_populates="module", cascade="all, delete-orphan", order_by="LectureVideo.order",
    )
    items: Mapped[list["ModuleItem"]] = relationship(
        back_populates="module", cascade="all, delete-orphan", order_by="ModuleItem.order",
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id, "course_id": self.course_id,
            "title": self.title, "order": self.order,
        }


# ──────────────────────────────────────────────────────────────────────────────
# LectureVideo  (table: lecture_videos)
# ──────────────────────────────────────────────────────────────────────────────

class LectureVideo(Base):
    """A single lecture/video resource within a Module."""

    __tablename__ = "lecture_videos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    module_id: Mapped[int] = mapped_column(ForeignKey("modules.id"))
    title: Mapped[str] = mapped_column(String(200))
    video_url: Mapped[str] = mapped_column(String(500))       # YouTube / hosted URL
    duration_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Exact media metadata in seconds.  This is the analytics source of truth;
    # duration_minutes remains for backwards-compatible authoring/display.
    duration_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    transcript_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    transcript_status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False
    )
    trainer_draft_transcript: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    public_transcript: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    module: Mapped["Module"] = relationship(back_populates="videos")

    def to_dict(self) -> dict:
        return {
            "id": self.id, "module_id": self.module_id,
            "title": self.title, "video_url": self.video_url,
            "duration_minutes": self.duration_minutes, "order": self.order,
            "duration_seconds": self.duration_seconds,
        }


class VideoEvent(Base):
    """A pause or backward seek emitted by a learner while viewing a lecture."""

    __tablename__ = "video_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lecture_id: Mapped[int] = mapped_column(ForeignKey("lecture_videos.id"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(12))  # pause | rewind
    video_timestamp_seconds: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ModuleItem(Base):
    """A flexible learning resource attached to a module."""

    __tablename__ = "module_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    module_id: Mapped[int] = mapped_column(ForeignKey("modules.id"))
    type: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(200))
    content_url: Mapped[str] = mapped_column(String(500))
    transcript_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    transcript_status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False
    )
    trainer_draft_transcript: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    public_transcript: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    module: Mapped["Module"] = relationship(back_populates="items")


# ──────────────────────────────────────────────────────────────────────────────
# Enrollment  (table: bookings — preserves existing data)
# ──────────────────────────────────────────────────────────────────────────────

class Enrollment(Base):
    """Learner ↔ Course enrollment record.  status ∈ {'Enrolled', 'Completed', 'Cancelled'}."""

    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id"), name="trainee_id",
    )
    learner_id = synonym("user_id")
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"))
    status: Mapped[str] = mapped_column(String(20), default="active")
    enrolled_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, name="booking_date")
    progress_percentage: Mapped[float] = mapped_column(Float, default=0.0, name="progress_pct")
    progress_pct = synonym("progress_percentage")

    learner: Mapped["User"] = relationship(
        back_populates="enrollments", foreign_keys=[user_id],
    )
    course: Mapped["Course"] = relationship(back_populates="enrollments")

    # ── Backward-compat aliases (used by pre-refactor templates) ──────
    @property
    def booking_date(self) -> datetime:
        """Alias for enrolled_at — keeps old templates working."""
        return self.enrolled_at

    @property
    def trainee(self) -> "User":
        """Alias for learner — keeps old templates working."""
        return self.learner

    @property
    def trainee_id(self) -> int:
        """Alias for learner_id — keeps old code working."""
        return self.learner_id

    def to_dict(self) -> dict:
        return {
            "id": self.id, "user_id": self.user_id,
            "course_id": self.course_id, "status": self.status,
            "enrolled_at": self.enrolled_at.isoformat(),
            "progress_percentage": self.progress_percentage,
        }


# ──────────────────────────────────────────────────────────────────────────────
# Assessment  (table: assessments)
# ──────────────────────────────────────────────────────────────────────────────

class Assessment(Base):
    """Quiz/assignment result for a learner in a course."""

    __tablename__ = "assessments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"))
    learner_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    title: Mapped[str] = mapped_column(String(200))
    score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)   # 0–100
    max_score: Mapped[float] = mapped_column(Float, default=100.0)
    feedback: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    course: Mapped["Course"] = relationship(back_populates="assessments")
    learner: Mapped["User"] = relationship(
        back_populates="assessments_taken", foreign_keys=[learner_id],
    )

    @property
    def percentage(self) -> Optional[float]:
        if self.score is not None and self.max_score:
            return round(self.score / self.max_score * 100, 1)
        return None


# ──────────────────────────────────────────────────────────────────────────────
# Doubt  (table: doubts)
# ──────────────────────────────────────────────────────────────────────────────

class Doubt(Base):
    """A question raised by a learner in a course, optionally answered by the trainer."""

    __tablename__ = "doubts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"))
    learner_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_anonymous: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    video_timestamp_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    is_resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    asked_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    answered_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    course: Mapped["Course"] = relationship(back_populates="doubts")
    learner: Mapped["User"] = relationship(
        back_populates="doubts_asked", foreign_keys=[learner_id],
    )


# ──────────────────────────────────────────────────────────────────────────────
# TelemetryLog  (table: telemetry_logs)
# ──────────────────────────────────────────────────────────────────────────────

class TelemetryLog(Base):
    """Playback events emitted by the trainee video player."""

    __tablename__ = "telemetry_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    course_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("courses.id"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(80))   # e.g. 'video_watch', 'quiz_submit'
    video_timestamp: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    client_timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )
    # Retained for compatibility with earlier telemetry records.
    entity_type: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)  # 'course', 'module', 'video'
    entity_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    metadata_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON string
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="telemetry_logs")


# ──────────────────────────────────────────────────────────────────────────────
# CompetencyProfile  (table: competency_profiles)
# ──────────────────────────────────────────────────────────────────────────────

class CompetencyProfile(Base):
    """Skills, qualifications, and certificates for a user (learner or trainer)."""

    __tablename__ = "competency_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id"), unique=True,
    )
    skills: Mapped[Optional[str]] = mapped_column(Text, nullable=True)       # comma-separated
    qualifications: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    certifications: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    linkedin_url: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    github_url: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    portfolio_url: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="competency_profile")

    def skills_list(self) -> list[str]:
        if not self.skills:
            return []
        return [s.strip() for s in self.skills.split(",") if s.strip()]

    def certs_list(self) -> list[str]:
        if not self.certifications:
            return []
        return [c.strip() for c in self.certifications.split(",") if c.strip()]


# ──────────────────────────────────────────────────────────────────────────────
# ChatMessage  (table: chat_messages — unchanged)
# ──────────────────────────────────────────────────────────────────────────────

class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sender_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    recipient_id: Mapped[Optional[int]] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    room_type: Mapped[str] = mapped_column(String(20))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    is_anonymous: Mapped[bool] = mapped_column(Boolean, default=False)

    sender: Mapped["User"] = relationship(foreign_keys=[sender_id])
    recipient: Mapped[Optional["User"]] = relationship(foreign_keys=[recipient_id])

    def to_dict(self) -> dict:
        display_name = "Anonymous Trainee" if self.is_anonymous else (
            self.sender.name if self.sender else None
        )
        return {
            "id": self.id, "sender_id": self.sender_id,
            "sender_name": display_name,
            "user": display_name,
            "role": self.sender.role if self.sender else None,
            "recipient_id": self.recipient_id, "room_type": self.room_type,
            "body": self.body, "created_at": self.created_at.isoformat(),
            "anonymous": self.is_anonymous,
        }


# ──────────────────────────────────────────────────────────────────────────────
# ChatRoomRead  (table: chat_room_reads — unchanged)
# ──────────────────────────────────────────────────────────────────────────────

class ChatRoomRead(Base):
    __tablename__ = "chat_room_reads"
    __table_args__ = (UniqueConstraint("account_id", "room_key", name="uq_chat_room_read"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    room_key: Mapped[str] = mapped_column(String(80))
    last_read_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ──────────────────────────────────────────────────────────────────────────────
# Legacy alias — existing code that imports Account still works
# ──────────────────────────────────────────────────────────────────────────────
Account = User
Booking = Enrollment
