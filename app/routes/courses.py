"""Database-backed trainee catalog, enrolment, and learning routes."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.extensions import SessionLocal
from app.models import Course, Enrollment, LectureVideo, Module, ModuleItem, User
from app.services.video_service import heatmap_for_video

router = APIRouter()


def _current_trainee(request: Request, db) -> User | None:
    from app.decorators import current_account

    user = current_account(request, db)
    if user and user.role == "trainee" and user.is_active:
        return user
    return None


def _course(course_id: int, db) -> Course:
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    return course


def _enrollment(db, user_id: int, course_id: int):
    return (
        db.query(Enrollment)
        .filter(
            Enrollment.user_id == user_id,
            Enrollment.course_id == course_id,
            Enrollment.status.in_(("active", "Enrolled")),
        )
        .first()
    )


def _group_transcript_segments(segments, group_size: int = 4) -> list[dict]:
    grouped = []
    for index in range(0, len(segments), group_size):
        chunk = segments[index:index + group_size]
        if not chunk:
            continue
        grouped.append({
            "start": chunk[0].get("start", 0),
            "end": chunk[-1].get("end", chunk[0].get("start", 0)),
            "text": " ".join(str(segment.get("text", "")).strip() for segment in chunk).strip(),
        })
    return grouped


def _auth_redirect(request: Request) -> RedirectResponse:
    role = request.session.get("role")
    if role == "trainer":
        return RedirectResponse("/trainer/dashboard", status_code=303)
    if role == "admin":
        return RedirectResponse("/admin/dashboard", status_code=303)
    return RedirectResponse("/auth/login", status_code=303)


@router.get("/courses", name="courses.catalog")
async def catalog(request: Request):
    from app import render

    with SessionLocal() as db:
        user = _current_trainee(request, db)
        if not user:
            return _auth_redirect(request)
        courses = db.query(Course).filter(Course.is_published.is_(True)).order_by(Course.created_at.desc()).all()
        enrolled_ids = {
            enrollment.course_id
            for enrollment in db.query(Enrollment).filter(
                Enrollment.user_id == user.id,
                Enrollment.status.in_(("active", "Enrolled")),
            )
        }
        return render(
            request,
            db,
            "learner/catalog.html",
            courses=courses,
            enrolled_ids=enrolled_ids,
        )


@router.get("/courses/{course_id}", name="courses.summary")
async def course_summary(request: Request, course_id: int):
    from app import render

    with SessionLocal() as db:
        user = _current_trainee(request, db)
        if not user:
            return _auth_redirect(request)
        course = _course(course_id, db)
        if not course.is_published:
            raise HTTPException(404, detail="Course not found")
        enrolled_count = sum(
            1 for enrollment in course.enrollments
            if str(enrollment.status).lower() not in {"cancelled", "canceled"}
        )
        return render(
            request,
            db,
            "learner/course_summary.html",
            course=course,
            enrolled=bool(_enrollment(db, user.id, course.id)),
            available_slots=max(0, int(course.total_slots or 0) - enrolled_count),
        )


@router.post("/courses/{course_id}/enroll", name="courses.enroll")
async def enroll(request: Request, course_id: int):
    from app import flash

    with SessionLocal() as db:
        user = _current_trainee(request, db)
        if not user:
            return _auth_redirect(request)
        course = _course(course_id, db)
        if not course.is_published:
            raise HTTPException(404, detail="Course not found")
        existing = (
            db.query(Enrollment)
            .filter(
                Enrollment.user_id == user.id,
                Enrollment.course_id == course.id,
            )
            .first()
        )
        active_count = sum(
            1 for enrollment in course.enrollments
            if str(enrollment.status).lower() not in {"cancelled", "canceled"}
        )
        available_slots = max(0, int(course.total_slots or 0) - active_count)
        if not existing and available_slots <= 0:
            flash(request, "This course is currently full.", "warning")
            return RedirectResponse(f"/courses/{course.id}", status_code=303)
        if not existing:
            db.add(Enrollment(user_id=user.id, course_id=course.id, status="active"))
            db.commit()
            course.available_slots = max(0, course.total_slots - active_count - 1)
            db.commit()
            flash(request, f"You are enrolled in {course.title}.", "success")
        elif existing.status not in ("active", "Enrolled"):
            existing.status = "active"
            db.commit()
            flash(request, f"You rejoined {course.title}.", "success")
        else:
            flash(request, f"You are already enrolled in {course.title}.", "info")
        return RedirectResponse(
            f"/courses/{course.id}/learn", status_code=303
        )


@router.post("/courses/{course_id}/join", name="courses.join")
async def join(request: Request, course_id: int):
    return await enroll(request, course_id)


@router.get("/courses/{course_id}/learn", name="courses.learn")
async def learn_course(request: Request, course_id: int):
    from app import flash, render

    with SessionLocal() as db:
        user = _current_trainee(request, db)
        if not user:
            return _auth_redirect(request)
        course = _course(course_id, db)
        enrollment = _enrollment(db, user.id, course.id)
        if not enrollment:
            flash(request, "Enroll in this course before starting the lessons.", "warning")
            return RedirectResponse("/learner/dashboard", status_code=303)
        videos = (
            db.query(LectureVideo)
            .join(LectureVideo.module)
            .filter(Module.course_id == course.id, Module.is_published.is_(True),
                    LectureVideo.is_published.is_(True))
            .order_by(Module.order, LectureVideo.order)
            .all()
        )
        items = (
            db.query(ModuleItem)
            .join(ModuleItem.module)
            .filter(Module.course_id == course.id, Module.is_published.is_(True),
                    ModuleItem.is_published.is_(True))
            .order_by(Module.order, ModuleItem.order)
            .all()
        )
        requested = request.query_params.get("lecture_id")
        active_video = (
            db.get(LectureVideo, int(requested))
            if requested and requested.isdigit()
            else None
        )
        if not active_video or active_video.module.course_id != course.id or not active_video.is_published or not active_video.module.is_published:
            active_video = videos[0] if videos else None
        requested_item = request.query_params.get("item_id")
        active_item = (
            db.get(ModuleItem, int(requested_item))
            if requested_item and requested_item.isdigit()
            else None
        )
        if active_item and (active_item.module.course_id != course.id or not active_item.is_published or not active_item.module.is_published):
            active_item = None
        transcript_source = (
            active_video.public_transcript
            if active_video and active_video.public_transcript
            else course.public_transcript
        )
        if active_item and active_item.public_transcript:
            transcript_source = active_item.public_transcript
        try:
            transcript_segments = json.loads(transcript_source or "[]")
            if not isinstance(transcript_segments, list):
                transcript_segments = []
            grouped_transcript = _group_transcript_segments(transcript_segments)
            transcript = json.dumps(grouped_transcript)
        except (TypeError, ValueError):
            grouped_transcript = []
            transcript = "[]"
        return render(
            request,
            db,
            "learner/lecture.html",
            course=course,
            enrollment=enrollment,
            videos=videos,
            items=items,
            lecture=active_video,
            active_item=active_item,
            heatmap=heatmap_for_video(db, active_video) if active_video else [],
            transcript=transcript,
            grouped_transcript=grouped_transcript,
        )
