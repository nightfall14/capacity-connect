"""Video telemetry, heatmap, and transcript Q&A endpoints."""

from __future__ import annotations

import math

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.extensions import SessionLocal
from app.models import Doubt, LectureVideo, TelemetryLog, User, VideoEvent
from app.services.video_service import (
    EVENT_TYPES,
    confusion_heatmap_for_lecture,
    heatmap_for_video,
    lecture_duration_seconds,
    transcript_match,
)

router = APIRouter()


def _current_user(request: Request, db) -> User | None:
    from app.decorators import current_account
    user = current_account(request, db)
    return user if user and user.is_active else None


@router.post("/api/lectures/{lecture_id}/duration")
async def record_lecture_duration(request: Request, lecture_id: int):
    """Cache duration reported by loaded media metadata, in seconds."""
    try:
        duration_seconds = float((await request.json())["duration_seconds"])
    except (KeyError, TypeError, ValueError):
        return JSONResponse({"error": "Invalid video duration."}, status_code=422)
    if not math.isfinite(duration_seconds) or duration_seconds <= 0:
        return JSONResponse({"error": "Invalid video duration."}, status_code=422)

    with SessionLocal() as db:
        user = _current_user(request, db)
        lecture = db.get(LectureVideo, lecture_id)
        if not user:
            return JSONResponse({"error": "Authentication required"}, status_code=401)
        if not lecture:
            return JSONResponse({"error": "Lecture not found"}, status_code=404)
        # A saved exact duration is authoritative.  duration_minutes is only
        # a legacy authoring estimate, so it must not override media metadata.
        if lecture.duration_seconds is None:
            lecture.duration_seconds = duration_seconds
            db.commit()
        return {"duration_seconds": lecture_duration_seconds(lecture)}


@router.post("/api/lectures/{lecture_id}/video-events")
async def capture_video_event(request: Request, lecture_id: int):
    """Persist one high-signal playback event without slowing the player."""
    try:
        payload = await request.json()
        event_type = str(payload["event_type"]).lower()
        timestamp = float(payload["video_timestamp_seconds"])
    except (KeyError, TypeError, ValueError):
        return JSONResponse({"error": "Invalid video event payload."}, status_code=422)
    if event_type not in {"pause", "rewind"} or not math.isfinite(timestamp) or timestamp < 0:
        return JSONResponse({"error": "Invalid video event."}, status_code=422)

    with SessionLocal() as db:
        user = _current_user(request, db)
        lecture = db.get(LectureVideo, lecture_id)
        if not user:
            return JSONResponse({"error": "Authentication required"}, status_code=401)
        if not lecture:
            return JSONResponse({"error": "Lecture not found"}, status_code=404)
        duration = lecture_duration_seconds(lecture)
        if duration is not None and timestamp > duration:
            return JSONResponse({"error": "Timestamp exceeds lecture duration."}, status_code=422)
        db.add(VideoEvent(
            lecture_id=lecture.id,
            account_id=user.id,
            event_type=event_type,
            video_timestamp_seconds=timestamp,
        ))
        db.commit()
    return {"ok": True}


@router.get("/api/lectures/{lecture_id}/confusion-heatmap")
async def lecture_confusion_heatmap(request: Request, lecture_id: int):
    with SessionLocal() as db:
        user = _current_user(request, db)
        lecture = db.get(LectureVideo, lecture_id)
        if not user:
            return JSONResponse({"error": "Authentication required"}, status_code=401)
        if not lecture:
            return JSONResponse({"error": "Lecture not found"}, status_code=404)
        if user.role not in {"trainer", "admin"}:
            return JSONResponse({"error": "Trainer access required"}, status_code=403)
        if user.role == "trainer" and lecture.module.course.trainer_id != user.id:
            return JSONResponse({"error": "Forbidden"}, status_code=403)
        return confusion_heatmap_for_lecture(db, lecture_id)


@router.get("/api/telemetry/heatmap/{video_id}")
async def telemetry_heatmap(request: Request, video_id: int):
    with SessionLocal() as db:
        if not _current_user(request, db):
            return JSONResponse({"error": "Authentication required"}, status_code=401)
        video = db.get(LectureVideo, video_id)
        if not video:
            return JSONResponse({"error": "Video not found"}, status_code=404)
        buckets = heatmap_for_video(db, video)
        total_duration_seconds = lecture_duration_seconds(video) or 0
        return {
            "video_id": video_id,
            "total_duration": total_duration_seconds,
            "total_duration_seconds": total_duration_seconds,
            "buckets": buckets,
        }


@router.post("/api/lecture/{video_id}/ask")
async def ask_about_lecture(request: Request, video_id: int):
    payload = await request.json()
    with SessionLocal() as db:
        user = _current_user(request, db)
        video = db.get(LectureVideo, video_id)
        if not user:
            return JSONResponse({"error": "Authentication required"}, status_code=401)
        if not video:
            return JSONResponse({"error": "Video not found"}, status_code=404)
        question = str(payload.get("question", "")).strip()
        if not question:
            return JSONResponse({"error": "Question is required"}, status_code=422)
        match = transcript_match(question)
        try:
            timestamp = float(payload.get("timestamp", 0))
        except (TypeError, ValueError):
            timestamp = 0.0
        db.add(Doubt(course_id=video.module.course_id, learner_id=user.id,
                     question=question, answer=match["answer"],
                     is_anonymous=bool(payload.get("anonymous", False)),
                     video_timestamp_seconds=timestamp))
        db.commit()
        return match
