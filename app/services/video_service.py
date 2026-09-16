"""Video telemetry, transcript matching, and confusion aggregation."""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import and_, or_

from app.models import LectureVideo, TelemetryLog, VideoEvent

TRANSCRIPT_PATH = Path(__file__).resolve().parents[1] / "static/uploads/transcripts/lecture1.json"
EVENT_TYPES = {"PAUSE", "REWIND", "SEEK"}
CONFUSION_BUCKET_SECONDS = 10


def lecture_duration_seconds(video: LectureVideo) -> int | None:
    """Return the known media duration; never turn missing metadata into 60s."""
    if video.duration_seconds is not None and float(video.duration_seconds) > 0:
        return max(1, round(float(video.duration_seconds)))
    if video.duration_minutes is not None and int(video.duration_minutes) > 0:
        return int(video.duration_minutes) * 60
    return None


def transcript_match(question: str) -> dict:
    try:
        chunks = json.loads(TRANSCRIPT_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        chunks = []
    words = {word.lower().strip(".,?!:;") for word in question.split() if len(word) > 2}
    best = max(
        chunks,
        key=lambda chunk: len(words & set(chunk["text"].lower().split())),
        default={"start": 0, "text": "Review this part of the lecture and discuss it with your trainer."},
    )
    minute, second = divmod(int(best["start"]), 60)
    return {
        "answer": f"Related lecture section: {best['text']}",
        "target_seconds": best["start"],
        "jump_label": f"Jump to {minute:02d}:{second:02d}",
    }


def _heatmap_color(score: float) -> str:
    """Interpolate green → amber → red for a normalized score."""
    score = min(1.0, max(0.0, score))
    green, amber, red = (34, 197, 94), (245, 158, 11), (239, 68, 68)
    start, end, progress = (green, amber, score * 2) if score <= 0.5 else (amber, red, (score - 0.5) * 2)
    rgb = tuple(round(a + (b - a) * progress) for a, b in zip(start, end))
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def confusion_heatmap_for_lecture(db, lecture_id: int) -> dict:
    """Aggregate pause/rewind signals into normalized ten-second buckets."""
    lecture = db.get(LectureVideo, lecture_id)
    if not lecture:
        raise LookupError("Lecture not found")

    duration_seconds = lecture_duration_seconds(lecture)
    if duration_seconds is None:
        return {
            "lecture_id": lecture.id,
            "duration_seconds": None,
            "bucket_size_seconds": CONFUSION_BUCKET_SECONDS,
            "buckets": [],
        }
    buckets = [
        {
            "index": index,
            "start_seconds": index * CONFUSION_BUCKET_SECONDS,
            "end_seconds": min((index + 1) * CONFUSION_BUCKET_SECONDS, duration_seconds),
            "pause_count": 0,
            "rewind_count": 0,
            "raw_score": 0,
        }
        for index in range((duration_seconds + CONFUSION_BUCKET_SECONDS - 1) // CONFUSION_BUCKET_SECONDS)
    ]
    for event in db.query(VideoEvent).filter(VideoEvent.lecture_id == lecture_id).all():
        index = min(len(buckets) - 1, max(0, int(event.video_timestamp_seconds // CONFUSION_BUCKET_SECONDS)))
        bucket = buckets[index]
        if event.event_type == "pause":
            bucket["pause_count"] += 1
            bucket["raw_score"] += 1
        elif event.event_type == "rewind":
            bucket["rewind_count"] += 1
            bucket["raw_score"] += 2

    peak_score = max((bucket["raw_score"] for bucket in buckets), default=0)
    for bucket in buckets:
        normalized = bucket["raw_score"] / peak_score if peak_score else 0.0
        bucket["normalized_score"] = round(normalized, 4)
        bucket["color_hex"] = _heatmap_color(normalized)

    return {
        "lecture_id": lecture.id,
        "duration_seconds": duration_seconds,
        "bucket_size_seconds": CONFUSION_BUCKET_SECONDS,
        "buckets": buckets,
    }


def heatmap_for_video(db, video: LectureVideo) -> list[dict]:
    duration = lecture_duration_seconds(video)
    if duration is None:
        return []
    bucket_size = 5
    buckets = [
        {
            "index": i,
            "bucket": i,
            "start_seconds": i * bucket_size,
            "end_seconds": min((i + 1) * bucket_size, duration),
            "pause_count": 0,
            "rewind_count": 0,
            "event_count": 0,
        }
        for i in range((duration + bucket_size - 1) // bucket_size)
    ]
    logs = db.query(TelemetryLog).filter(
        or_(
            and_(
                TelemetryLog.entity_type == "video",
                TelemetryLog.entity_id == video.id,
            ),
            and_(
                TelemetryLog.course_id == video.module.course_id,
                TelemetryLog.entity_id.is_(None),
            ),
        ),
        TelemetryLog.event_type.in_(
            (
                "PLAY", "PAUSE", "SEEK", "HEARTBEAT", "REWIND",
                "MEDIA_PLAY", "MEDIA_PAUSE", "MEDIA_SEEK", "MEDIA_HEARTBEAT",
            )
        ),
    ).all()
    for log in logs:
        try:
            metadata = json.loads(log.metadata_json or "{}")
            timestamp = float(
                log.video_timestamp
                if log.video_timestamp is not None
                else metadata.get("timestamp", 0)
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            timestamp = 0
        index = min(len(buckets) - 1, max(0, int(timestamp // bucket_size)))
        bucket = buckets[index]
        bucket["event_count"] += 1
        if log.event_type in {"PAUSE", "MEDIA_PAUSE", "REWIND", "SEEK", "MEDIA_SEEK"}:
            if log.event_type in {"PAUSE", "MEDIA_PAUSE"}:
                bucket["pause_count"] += 1
            else:
                bucket["rewind_count"] += 1
    for bucket in buckets:
        friction = bucket["pause_count"] + bucket["rewind_count"]
        bucket["start_time"] = bucket["start_seconds"]
        bucket["end_time"] = bucket["end_seconds"]
        bucket["count"] = bucket["event_count"]
        bucket["friction_score"] = friction
        bucket["score"] = friction
        if bucket["event_count"] == 0:
            bucket["status"], bucket["color_hex"] = "unseen", "#E2E8F0"
        elif friction == 0:
            bucket["status"], bucket["color_hex"] = "smooth", "#10B981"
        elif friction <= 2:
            bucket["status"], bucket["color_hex"] = "yellow", "#FACC15"
        elif friction <= 5:
            bucket["status"], bucket["color_hex"] = "orange", "#FB923C"
        else:
            bucket["status"], bucket["color_hex"] = "red", "#EF4444"
    return buckets
