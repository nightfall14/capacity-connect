"""JSON APIs used by the trainee learning shell."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.extensions import SessionLocal
from app.models import LectureVideo, TelemetryLog, User
from app.services import lecture_qa_service
from app.services.transcription_service import transcription_progress
import json

router = APIRouter()


@router.get("/api/transcription/status/{module_id}")
async def transcription_status(request: Request, module_id: int):
    with SessionLocal() as db:
        user = _current_user(request, db)
        video = db.get(LectureVideo, module_id)
        if not user or not video:
            return JSONResponse({"error": "Not found"}, status_code=404)
        if user.role not in {"trainer", "admin"}:
            return JSONResponse({"error": "Trainer or admin access required."}, status_code=403)
        if user.role == "trainer" and video.module.course.trainer_id != user.id:
            return JSONResponse({"error": "Forbidden"}, status_code=403)
        state = transcription_progress(module_id)
        if video.transcript_status == "completed":
            state = {"status": "completed", "progress": 100}
        elif video.transcript_status == "failed":
            error = {}
            try:
                error = json.loads(video.trainer_draft_transcript or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
            state = {
                "status": "failed",
                "progress": 100,
                "error": error.get("error", "Transcript generation failed."),
            }
        return state


@router.get("/api/transcription/preview/{module_id}")
async def transcription_preview(request: Request, module_id: int):
    with SessionLocal() as db:
        user = _current_user(request, db)
        video = db.get(LectureVideo, module_id)
        if not user or not video:
            return JSONResponse({"error": "Not found"}, status_code=404)
        if user.role == "trainer" and video.module.course.trainer_id != user.id:
            return JSONResponse({"error": "Forbidden"}, status_code=403)
        try:
            segments = json.loads(video.trainer_draft_transcript or "[]")
        except (TypeError, ValueError, json.JSONDecodeError):
            segments = []
        return {"segments": segments if isinstance(segments, list) else []}

VALID_EVENTS = {
    "PLAY", "PAUSE", "SEEK", "HEARTBEAT",
    "MEDIA_PLAY", "MEDIA_PAUSE", "MEDIA_SEEK", "MEDIA_HEARTBEAT",
}


def _current_trainee(request: Request, db) -> User | None:
    from app.decorators import current_account

    user = current_account(request, db)
    if user and user.is_active and user.role == "trainee":
        return user
    return None


def _current_user(request: Request, db) -> User | None:
    from app.decorators import current_account

    user = current_account(request, db)
    return user if user and user.is_active else None


@router.post("/api/lectures/{lecture_id}/qa")
async def lecture_qa(request: Request, lecture_id: int):
    """Answer a learner's question from the lecture transcript."""
    try:
        question = str((await request.json())["question"]).strip()
    except (KeyError, TypeError, ValueError):
        return JSONResponse({"error": "A question is required."}, status_code=422)
    if not question:
        return JSONResponse({"error": "A question is required."}, status_code=422)

    with SessionLocal() as db:
        user = _current_user(request, db)
        lecture = db.get(LectureVideo, lecture_id)
        if not user:
            return JSONResponse({"error": "Authentication required."}, status_code=401)
        if not lecture:
            return JSONResponse({"error": "Lecture not found."}, status_code=404)

        transcript_source = (
            lecture.public_transcript
            if lecture.public_transcript
            else lecture.module.course.public_transcript
        )
        try:
            transcript_chunks = json.loads(transcript_source or "[]")
            if not isinstance(transcript_chunks, list):
                transcript_chunks = []
        except (TypeError, ValueError, json.JSONDecodeError):
            transcript_chunks = []

        answer = lecture_qa_service.transcript_answer(question, transcript_chunks)
        if not answer:
            return {
                "matched": False,
                "message": "No matching answer found in this lecture transcript.",
            }
        return {
            "matched": True,
            "text": answer["text"],
            "start_seconds": answer["start_seconds"],
        }


@router.post("/api/telemetry")
async def ingest_telemetry(request: Request):
    try:
        payload = await request.json()
        user_id = int(payload["user_id"])
        course_id = int(payload["course_id"])
        event_type = str(payload["event_type"]).upper()
        video_timestamp = float(payload["video_timestamp"])
        video_id = payload.get("video_id")
        video_id = int(video_id) if video_id not in (None, "") else None
    except (KeyError, TypeError, ValueError):
        return JSONResponse({"error": "Invalid telemetry payload."}, status_code=422)

    if event_type not in VALID_EVENTS or video_timestamp < 0:
        return JSONResponse({"error": "Invalid telemetry event."}, status_code=422)

    with SessionLocal() as db:
        user = _current_trainee(request, db)
        if not user or user.id != user_id:
            return JSONResponse({"error": "Authentication required."}, status_code=401)
        if video_id is not None:
            video = db.get(LectureVideo, video_id)
            if not video or video.module.course_id != course_id:
                return JSONResponse({"error": "Invalid video for course."}, status_code=422)
        db.add(
            TelemetryLog(
                user_id=user_id,
                course_id=course_id,
                event_type=event_type,
                video_timestamp=video_timestamp,
                entity_type="video" if video_id else None,
                entity_id=video_id,
            )
        )
        db.commit()
        return {"ok": True}
