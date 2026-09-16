"""
Backward-compatibility shim.
All model definitions now live in app/models/core.py.
This file re-exports everything so existing imports of `app.models` still work.
"""

from app.models.core import (  # noqa: F401
    Account,
    Assessment,
    Booking,
    ChatMessage,
    ChatRoomRead,
    CompetencyProfile,
    Course,
    Doubt,
    Enrollment,
    LectureVideo,
    Module,
    TelemetryLog,
    User,
    VideoEvent,
)

__all__ = [
    "User", "Account", "Course", "Module", "LectureVideo",
    "Enrollment", "Booking", "Assessment", "Doubt",
    "TelemetryLog", "VideoEvent", "CompetencyProfile", "ChatMessage", "ChatRoomRead",
]
