"""
Capacity Connect — models package.
Import all ORM models here so they register with SQLAlchemy's metadata.
"""

from app.models.core import (
    Account,       # alias for User (backward compat)
    Assessment,
    Booking,       # alias for Enrollment (backward compat)
    ChatMessage,
    ChatRoomRead,
    CompetencyProfile,
    Course,
    Doubt,
    Enrollment,
    LectureVideo,
    Module,
    ModuleItem,
    TelemetryLog,
    User,
    VideoEvent,
)

__all__ = [
    "User",
    "Account",
    "Course",
    "Module",
    "ModuleItem",
    "LectureVideo",
    "Enrollment",
    "Booking",
    "Assessment",
    "Doubt",
    "TelemetryLog",
    "VideoEvent",
    "CompetencyProfile",
    "ChatMessage",
    "ChatRoomRead",
]
