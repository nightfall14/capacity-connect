"""
Trainer routes — course management, module/video creation, profile, participants.
All routes require role='trainer' and is_approved=True.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
import json
from secrets import token_hex
from pathlib import Path
from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse

from app.extensions import SessionLocal
from app.models import Course, Doubt, Enrollment, LectureVideo, Module, ModuleItem, User, CompetencyProfile
from app.services.curriculum_service import build_curriculum_insights
from app.services.video_service import heatmap_for_video
from app.services.transcription_service import (
    generate_transcript, parse_segments, set_transcription_progress,
)
from app.services.lecture_qa_service import parse_timestamped_transcript
from app.services.readiness_service import readiness_score_for_course

router = APIRouter()

VALID_STATUSES = ("Draft", "In Progress", "Completed")
ALLOWED_NOTE_TYPES = {".pdf": "pdf", ".pptx": "ppt"}
NOTES_DIRECTORY = Path(__file__).resolve().parents[1] / "static" / "uploads" / "notes"


def _guard(request: Request, db) -> User | None:
    from app.decorators import current_account

    user = current_account(request, db)
    if user and user.role == "trainer" and user.is_approved and user.is_active:
        return user
    return None


def _own_course(db, trainer_id: int, course_id: int) -> Course:
    course = db.get(Course, course_id)
    if not course or course.trainer_id != trainer_id:
        raise HTTPException(403)
    return course


def _transcribe_video(video_id: int, source_url: str) -> None:
    """Run Whisper outside the request and persist the result."""
    with SessionLocal() as db:
        video = db.get(LectureVideo, video_id)
        if not video:
            return
        try:
            video.transcript_status = "generating"
            set_transcription_progress(video_id, "processing", 10)
            db.commit()
            set_transcription_progress(video_id, "processing", 35)
            segments = generate_transcript(source_url)
            set_transcription_progress(video_id, "processing", 85)
            video.trainer_draft_transcript = json.dumps(segments)
            video.transcript_status = "draft_ready"
            video.module.course.has_unpublished_changes = True
            set_transcription_progress(video_id, "completed", 100)
        except (RuntimeError, OSError, ValueError) as exc:
            video.transcript_status = "failed"
            video.transcript_json = json.dumps({"error": str(exc)})
            set_transcription_progress(video_id, "failed", 100)
        db.commit()


# ──────────────────────────────────────────────────────────────────────────────
# Dashboard
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/dashboard", name="trainer.dashboard")
async def dashboard(request: Request):
    from app import render

    with SessionLocal() as db:
        trainer = _guard(request, db)
        if not trainer:
            return RedirectResponse("/auth/login", status_code=303)
        courses = (
            db.query(Course)
            .filter_by(trainer_id=trainer.id)
            .order_by(Course.created_at.desc())
            .all()
        )
        course_ids = [course.id for course in courses]
        enrollments = (
            db.query(Enrollment)
            .filter(
                Enrollment.course_id.in_(course_ids),
                Enrollment.status.notin_(("Cancelled", "cancelled")),
            )
            .all()
            if course_ids else []
        )
        unresolved_doubts = (
            db.query(Doubt)
            .filter(
                Doubt.course_id.in_(course_ids),
                Doubt.is_resolved.is_(False),
            )
            .count()
            if course_ids else 0
        )
        high_confusion_zones = 0
        for course in courses:
            for module in course.modules:
                for video in module.videos:
                    high_confusion_zones += sum(
                        bucket["score"] > 3
                        for bucket in heatmap_for_video(db, video)
                    )
        stats = {
            "active_courses": len(courses),
            "total_trainees": len(enrollments),
            "unresolved_doubts": unresolved_doubts,
            "curriculum_alerts": high_confusion_zones,
        }
        return render(request, db, "trainer/dashboard.html", courses=courses, stats=stats)


@router.get("/readiness", name="trainer.readiness")
async def readiness(request: Request):
    """Show individual readiness only for trainees in this trainer's courses."""
    from app import render

    with SessionLocal() as db:
        trainer = _guard(request, db)
        if not trainer:
            return RedirectResponse("/auth/login", status_code=303)
        courses = db.query(Course).filter(Course.trainer_id == trainer.id).order_by(Course.title).all()
        course_readiness = []
        for course in courses:
            enrollments = db.query(Enrollment).filter(
                Enrollment.course_id == course.id,
                Enrollment.status.in_(("active", "Enrolled")),
            ).all()
            learners = [
                {
                    "name": enrollment.learner.name,
                    "email": enrollment.learner.email,
                    "score": readiness_score_for_course(db, enrollment.user_id, course.id),
                }
                for enrollment in enrollments
            ]
            course_readiness.append({
                "course": course,
                "learners": sorted(learners, key=lambda learner: learner["score"]),
            })
        return render(request, db, "trainer/readiness.html", course_readiness=course_readiness)


@router.api_route("/courses/create", methods=["GET", "POST"], name="trainer.create_course")
async def create_course(request: Request):
    """Create a published course owned by the authenticated trainer."""
    from app import flash, render

    with SessionLocal() as db:
        trainer = _guard(request, db)
        if not trainer:
            return RedirectResponse("/auth/login", status_code=303)
        if request.method == "GET":
            return render(request, db, "trainer/course_form.html", form={})

        form = await request.form()
        name = str(form.get("name", "")).strip()
        description = str(form.get("description", "")).strip() or None
        video_url = str(form.get("video_url", "")).strip() or None
        try:
            total_slots = max(1, int(form.get("total_slots", 100)))
        except (TypeError, ValueError):
            total_slots = 100
        generate_now = str(form.get("generate_transcript", "")).lower() in {
            "1", "true", "on", "yes",
        }
        if len(name) < 3:
            flash(request, "Course name must be at least 3 characters.", "danger")
            return render(request, db, "trainer/course_form.html", form=form)

        course = Course(
            name=name,
            description=description,
            trainer_id=trainer.id,
            status="In Progress",
            total_slots=total_slots,
            available_slots=total_slots,
            location="Online",
            difficulty="Moderate",
            duration="Self-paced",
            start_date=date.today(),
            end_date=date.today() + timedelta(days=365),
            video_url=video_url,
            transcript_status="none",
            is_published=False,
            has_unpublished_changes=True,
        )
        db.add(course)
        db.commit()
        db.refresh(course)
        if video_url and generate_now:
            try:
                course.trainer_draft_transcript = json.dumps(generate_transcript(video_url))
                course.transcript_status = "draft_ready"
                course.has_unpublished_changes = True
                db.commit()
            except (RuntimeError, OSError, ValueError) as exc:
                course.transcript_status = "failed"
                db.commit()
                flash(request, f"Course created, but transcript generation failed: {exc}", "warning")
        flash(request, f"Course '{course.name}' was created as a draft.", "success")
        return RedirectResponse("/trainer/dashboard", status_code=303)


@router.post("/courses/{course_id}/generate-transcript", name="trainer.generate_transcript")
async def generate_course_transcript(request: Request, course_id: int):
    from app import flash

    with SessionLocal() as db:
        trainer = _guard(request, db)
        if not trainer:
            return RedirectResponse("/auth/login", status_code=303)
        course = _own_course(db, trainer.id, course_id)
        if not course.video_url:
            flash(request, "Add a video URL before generating a transcript.", "danger")
            return RedirectResponse("/trainer/dashboard", status_code=303)
        course.transcript_status = "generating"
        db.commit()
        try:
            segments = generate_transcript(course.video_url)
            course.trainer_draft_transcript = json.dumps(segments)
            course.transcript_status = "draft_ready"
            course.has_unpublished_changes = True
            db.commit()
            flash(request, "Whisper transcript generated successfully.", "success")
        except (RuntimeError, OSError, ValueError) as exc:
            course.transcript_status = "failed"
            db.commit()
            flash(request, f"Transcript generation failed: {exc}", "danger")
        return RedirectResponse("/trainer/dashboard", status_code=303)


@router.api_route(
    "/courses/{course_id}/transcript",
    methods=["GET", "POST"],
    name="trainer.transcript",
)
async def transcript_editor(request: Request, course_id: int):
    from app import render, flash
    from fastapi.responses import JSONResponse

    with SessionLocal() as db:
        trainer = _guard(request, db)
        if not trainer:
            return RedirectResponse("/auth/login", status_code=303)
        course = _own_course(db, trainer.id, course_id)
        if request.method == "GET":
            try:
                segments = parse_segments(course.trainer_draft_transcript)
            except (ValueError, TypeError, json.JSONDecodeError):
                segments = []
            return render(
                request, db, "trainer/edit_transcript.html",
                course=course,
                segments=segments,
                transcript_json=course.trainer_draft_transcript or "[]",
                media_url=course.video_url or "",
            )

        try:
            payload = await request.json()
            segments = parse_segments(json.dumps(payload.get("segments", payload)))
        except (json.JSONDecodeError, TypeError, ValueError, AttributeError) as exc:
            return JSONResponse({"status": "error", "message": str(exc)}, status_code=422)
        course.trainer_draft_transcript = json.dumps(segments)
        course.transcript_status = "draft_ready"
        course.has_unpublished_changes = True
        db.commit()
        target = Path(__file__).resolve().parents[1] / "static" / "uploads" / "transcripts"
        target.mkdir(parents=True, exist_ok=True)
        (target / f"course_{course.id}.json").write_text(
            json.dumps(segments, indent=2), encoding="utf-8"
        )
        return JSONResponse(
            {"status": "success", "message": "Transcript updated successfully"}
        )


@router.api_route(
    "/modules/{module_id}/transcript/edit",
    methods=["GET", "POST"],
    name="trainer.module_transcript_edit",
)
async def module_transcript_edit(request: Request, module_id: int):
    from app import render
    from fastapi.responses import JSONResponse

    with SessionLocal() as db:
        trainer = _guard(request, db)
        if not trainer:
            return RedirectResponse("/auth/login", status_code=303)
        video = db.get(LectureVideo, module_id)
        if not video or video.module.course.trainer_id != trainer.id:
            raise HTTPException(404, "Transcript resource not found")
        if request.method == "POST":
            try:
                payload = await request.json()
                segments = parse_segments(json.dumps(payload.get("segments", payload)))
            except (json.JSONDecodeError, TypeError, ValueError, AttributeError) as exc:
                return JSONResponse({"status": "error", "message": str(exc)}, status_code=422)
            video.trainer_draft_transcript = json.dumps(segments)
            video.transcript_status = "draft_ready"
            video.module.course.has_unpublished_changes = True
            db.commit()
            return JSONResponse({"status": "success", "message": "Transcript updated successfully."})

        transcript_json = video.trainer_draft_transcript or video.public_transcript or "[]"
        return render(
            request,
            db,
            "trainer/edit_transcript.html",
            course=video.module.course,
            segments=[],
            transcript_json=transcript_json,
            transcript_resource=video,
            media_url=video.video_url,
        )


@router.get("/confusion/{video_id}", name="trainer.confusion")
async def confusion(request: Request, video_id: int):
    from app import render

    with SessionLocal() as db:
        trainer = _guard(request, db)
        if not trainer:
            return RedirectResponse("/auth/login", status_code=303)
        video = db.get(LectureVideo, video_id)
        if not video or video.module.course.trainer_id != trainer.id:
            raise HTTPException(404)
        heatmap = heatmap_for_video(db, video)
        doubts = [
            {"bucket": int((d.video_timestamp_seconds or 0) // 5)}
            for d in db.query(Doubt).filter_by(course_id=video.module.course_id).all()
            if d.video_timestamp_seconds is not None
        ]
        insights = build_curriculum_insights(heatmap, doubts)
        return render(request, db, "trainer/confusion.html",
                      video=video, heatmap=heatmap, insights=insights,
                      duration=max((bucket["end_seconds"] for bucket in heatmap), default=0))


@router.get("/modules/{module_id}/transcript/preview")
async def preview_module_transcript(request: Request, module_id: int):
    with SessionLocal() as db:
        trainer = _guard(request, db)
        if not trainer:
            return JSONResponse({"status": "error", "message": "Authentication required."}, status_code=401)
        resource = db.get(LectureVideo, module_id) or db.get(ModuleItem, module_id)
        if not resource or resource.module.course.trainer_id != trainer.id:
            raise HTTPException(404, "Transcript resource not found")
        raw = resource.trainer_draft_transcript or resource.public_transcript
        if not raw:
            return JSONResponse({"status": "error", "message": "No transcript found."})
        try:
            segments = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return JSONResponse({"status": "error", "message": "Stored transcript is invalid."}, status_code=422)
        if not isinstance(segments, list):
            return JSONResponse({"status": "error", "message": "No transcript found."})
        return JSONResponse({"status": "success", "data": segments})


@router.get("/courses/{course_id}/telemetry", name="trainer.telemetry")
async def course_telemetry(request: Request, course_id: int):
    from app import render

    with SessionLocal() as db:
        trainer = _guard(request, db)
        if not trainer:
            return RedirectResponse("/auth/login", status_code=303)
        course = _own_course(db, trainer.id, course_id)
        videos = [
            video
            for module in course.modules
            for video in module.videos
        ]
        heatmaps = [
            {"video": video, "buckets": heatmap_for_video(db, video)}
            for video in videos
        ]
        return render(
            request,
            db,
            "trainer/telemetry.html",
            course=course,
            heatmaps=heatmaps,
        )


# ──────────────────────────────────────────────────────────────────────────────
# Profile
# ──────────────────────────────────────────────────────────────────────────────

@router.api_route("/profile", methods=["GET", "POST"], name="trainer.profile")
async def profile(request: Request):
    from app import render, flash

    with SessionLocal() as db:
        trainer = _guard(request, db)
        if not trainer:
            return RedirectResponse("/auth/login", status_code=303)

        # Ensure competency profile exists
        cp = trainer.competency_profile
        if not cp:
            cp = CompetencyProfile(user_id=trainer.id)
            db.add(cp)
            db.commit()
            db.refresh(trainer)
            cp = trainer.competency_profile

        if request.method == "POST":
            form = await request.form()
            name = str(form.get("name", "")).strip()
            if len(name) < 3:
                flash(request, "Name must be at least 3 characters.", "danger")
                return RedirectResponse("/trainer/profile", status_code=303)

            trainer.name = name
            trainer.phone = str(form.get("phone", "")).strip()
            trainer.designation = str(form.get("designation", "")).strip() or None
            trainer.department = str(form.get("department", "")).strip() or None
            trainer.bio = str(form.get("bio", "")).strip() or None

            cp.skills = str(form.get("skills", "")).strip() or None
            cp.qualifications = str(form.get("qualifications", "")).strip() or None
            cp.certifications = str(form.get("certifications", "")).strip() or None
            cp.linkedin_url = str(form.get("linkedin_url", "")).strip() or None
            cp.github_url = str(form.get("github_url", "")).strip() or None
            cp.portfolio_url = str(form.get("portfolio_url", "")).strip() or None

            if form.get("password"):
                trainer.set_password(str(form["password"]))

            db.commit()
            request.session["name"] = trainer.name
            flash(request, "Profile updated successfully.", "success")
            return RedirectResponse("/trainer/profile", status_code=303)

        return render(request, db, "trainer/profile.html", trainer=trainer, cp=cp)


# ──────────────────────────────────────────────────────────────────────────────
# Course detail & management
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/courses/{course_id}", name="trainer.course_detail")
async def course_detail(request: Request, course_id: int):
    from app import render

    with SessionLocal() as db:
        trainer = _guard(request, db)
        if not trainer:
            return RedirectResponse("/auth/login", status_code=303)
        course = _own_course(db, trainer.id, course_id)
        enrollments = [
            enrollment for enrollment in course.enrollments
            if str(enrollment.status).lower() not in {"cancelled", "canceled"}
        ]
        completed = sum(
            str(enrollment.status).lower() in {"completed", "complete"}
            or float(enrollment.progress_percentage or 0) >= 100
            for enrollment in enrollments
        )
        confusion_alerts = sum(
            bucket["score"] > 3
            for module in course.modules
            for video in module.videos
            for bucket in heatmap_for_video(db, video)
        )
        return render(request, db, "trainer/course_detail.html",
                      course=course, valid_statuses=VALID_STATUSES,
                      enrolled_count=len(enrollments),
                      completion_rate=round(completed / len(enrollments) * 100) if enrollments else 0,
                      confusion_alerts=confusion_alerts)


@router.post("/courses/{course_id}/publish-changes", name="trainer.publish_changes")
async def publish_changes(request: Request, course_id: int):
    from app.decorators import current_account

    with SessionLocal() as db:
        actor = current_account(request, db)
        if not actor or not actor.is_active or actor.role not in {"trainer", "admin"}:
            return JSONResponse({"error": "Authentication required."}, status_code=401)
        course = db.get(Course, course_id)
        if not course or (actor.role == "trainer" and course.trainer_id != actor.id):
            return JSONResponse({"error": "Course not found."}, status_code=404)

        course.is_published = True
        course.has_unpublished_changes = False
        course.last_published_at = datetime.utcnow()
        export_segments = None
        if course.trainer_draft_transcript:
            course.public_transcript = course.trainer_draft_transcript
            course.transcript_json = course.public_transcript
            course.transcript_status = "published"
            try:
                export_segments = json.loads(course.public_transcript)
            except (TypeError, ValueError, json.JSONDecodeError):
                export_segments = None
        for module in course.modules:
            module.is_published = True
            for video in module.videos:
                video.is_published = True
                if video.trainer_draft_transcript:
                    video.public_transcript = video.trainer_draft_transcript
                    video.transcript_json = video.public_transcript
                    video.transcript_status = "published"
                    if export_segments is None:
                        try:
                            export_segments = json.loads(video.public_transcript)
                        except (TypeError, ValueError, json.JSONDecodeError):
                            export_segments = None
            for item in module.items:
                item.is_published = True
                if item.trainer_draft_transcript:
                    item.public_transcript = item.trainer_draft_transcript
                    item.transcript_json = item.public_transcript
                    item.transcript_status = "published"
        db.commit()
        if export_segments is not None:
            target = Path(__file__).resolve().parents[1] / "static" / "uploads" / "transcripts"
            target.mkdir(parents=True, exist_ok=True)
            (target / f"course_{course.id}.json").write_text(
                json.dumps(export_segments, indent=2), encoding="utf-8"
            )
        return JSONResponse({
            "status": "success",
            "message": "All saved changes and transcripts are now live for trainees.",
        })


@router.post("/courses/{course_id}/update-slots", name="trainer.update_slots")
async def update_slots(request: Request, course_id: int):
    from app import flash

    with SessionLocal() as db:
        trainer = _guard(request, db)
        if not trainer:
            return RedirectResponse("/auth/login", status_code=303)
        course = _own_course(db, trainer.id, course_id)
        form = await request.form()
        try:
            slots = int(form.get("total_slots", -1))
        except ValueError:
            slots = -1
        if slots > 0 and slots >= course.active_enrollments_count():
            course.total_slots = slots
            course.available_slots = max(0, slots - course.active_enrollments_count())
            course.has_unpublished_changes = True
            db.commit()
            flash(request, "Course capacity updated.", "success")
        else:
            flash(request, "Invalid available slots value.", "danger")
        return RedirectResponse(f"/trainer/courses/{course_id}", status_code=303)


@router.post(
    "/courses/{course_id}/modules/{module_id}/upload",
    name="trainer.upload_module_item",
)
async def upload_module_item(
    request: Request,
    course_id: int,
    module_id: int,
    file: UploadFile = File(...),
):
    from app import flash
    from secrets import token_hex

    with SessionLocal() as db:
        trainer = _guard(request, db)
        if not trainer:
            return RedirectResponse("/auth/login", status_code=303)
        course = _own_course(db, trainer.id, course_id)
        module = db.get(Module, module_id)
        if not module or module.course_id != course.id:
            raise HTTPException(404, "Module not found")
        suffix = Path(file.filename or "").suffix.lower()
        item_type = ALLOWED_NOTE_TYPES.get(suffix)
        if not item_type:
            flash(request, "Only PDF and PPTX notes can be uploaded.", "danger")
            return RedirectResponse(f"/trainer/courses/{course_id}", status_code=303)
        directory = NOTES_DIRECTORY
        directory.mkdir(parents=True, exist_ok=True)
        filename = f"{module.id}_{token_hex(8)}{suffix}"
        target = directory / filename
        target.write_bytes(await file.read())
        item = ModuleItem(
            module_id=module.id,
            type=item_type,
            title=Path(file.filename or filename).stem,
            content_url=f"/static/uploads/notes/{filename}",
            order=len(module.items) + 1,
            is_published=False,
        )
        db.add(item)
        course.has_unpublished_changes = True
        db.commit()
        flash(request, "Learning notes uploaded.", "success")
        return RedirectResponse(f"/trainer/courses/{course_id}", status_code=303)


def _remove_note_file(content_url: str | None) -> None:
    if not content_url or not content_url.startswith("/static/uploads/notes/"):
        return
    target = (Path(__file__).resolve().parents[1] / content_url.lstrip("/")).resolve()
    notes_root = NOTES_DIRECTORY.resolve()
    if target.parent == notes_root and target.is_file():
        target.unlink()


def _owned_module_item(db, trainer: User, item_id: int) -> ModuleItem:
    item = db.get(ModuleItem, item_id)
    if not item or item.module.course.trainer_id != trainer.id:
        raise HTTPException(404, "Module item not found")
    return item


@router.delete("/modules/items/{item_id}")
async def delete_module_item(request: Request, item_id: int):
    with SessionLocal() as db:
        trainer = _guard(request, db)
        if not trainer:
            return JSONResponse({"status": "error", "message": "Authentication required."}, status_code=401)
        item = _owned_module_item(db, trainer, item_id)
        course = item.module.course
        _remove_note_file(item.content_url)
        db.delete(item)
        course.has_unpublished_changes = True
        db.commit()
        return {"status": "success", "message": "Item deleted successfully."}


@router.put("/modules/items/{item_id}")
async def update_module_item(request: Request, item_id: int):
    with SessionLocal() as db:
        trainer = _guard(request, db)
        if not trainer:
            return JSONResponse({"status": "error", "message": "Authentication required."}, status_code=401)
        item = _owned_module_item(db, trainer, item_id)
        try:
            payload = await request.json()
        except ValueError:
            return JSONResponse({"status": "error", "message": "Invalid JSON body."}, status_code=422)
        title = payload.get("title")
        content_url = payload.get("content_url")
        if title is not None:
            item.title = str(title).strip() or item.title
        if content_url is not None:
            item.content_url = str(content_url).strip() or item.content_url
        item.module.course.has_unpublished_changes = True
        db.commit()
        return {"status": "success", "message": "Item updated successfully."}


@router.post("/modules/items/{item_id}/replace-file")
async def replace_module_item_file(
    request: Request, item_id: int, file: UploadFile = File(...),
):
    with SessionLocal() as db:
        trainer = _guard(request, db)
        if not trainer:
            return JSONResponse({"status": "error", "message": "Authentication required."}, status_code=401)
        item = _owned_module_item(db, trainer, item_id)
        suffix = Path(file.filename or "").suffix.lower()
        item_type = ALLOWED_NOTE_TYPES.get(suffix)
        if not item_type:
            return JSONResponse({"status": "error", "message": "Only PDF and PPTX files are supported."}, status_code=422)
        NOTES_DIRECTORY.mkdir(parents=True, exist_ok=True)
        filename = f"{item.module_id}_{token_hex(8)}{suffix}"
        target = NOTES_DIRECTORY / filename
        target.write_bytes(await file.read())
        old_url = item.content_url
        item.content_url = f"/static/uploads/notes/{filename}"
        item.type = item_type
        item.title = Path(file.filename or filename).stem
        item.module.course.has_unpublished_changes = True
        db.commit()
        _remove_note_file(old_url)
        return {"status": "success", "message": "File replaced successfully."}


@router.post("/modules/{item_id}/transcribe", name="trainer.transcribe_module_item")
async def transcribe_module_item(
    request: Request, item_id: int, background_tasks: BackgroundTasks
):
    from app import flash
    from app.decorators import current_account

    with SessionLocal() as db:
        trainer = current_account(request, db)
        if not trainer or not trainer.is_active:
            return JSONResponse({"error": "Authentication required."}, status_code=401)
        if trainer.role != "trainer" or not trainer.is_approved:
            return JSONResponse(
                {"error": "An approved trainer account is required."}, status_code=403
            )
        item = db.get(LectureVideo, item_id)
        if not item or item.module.course.trainer_id != trainer.id:
            raise HTTPException(404, "Video not found")
        item.transcript_status = "queued"
        item.trainer_draft_transcript = None
        item.module.course.has_unpublished_changes = True
        set_transcription_progress(item.id, "processing", 0)
        db.commit()
        background_tasks.add_task(_transcribe_video, item.id, item.video_url)
        return {"status": "queued", "progress": 0}


@router.post("/courses/{course_id}/update-status", name="trainer.update_status")
async def update_status(request: Request, course_id: int):
    from app import flash
    from app.routes.admin import _sync_enrollment_status

    with SessionLocal() as db:
        trainer = _guard(request, db)
        if not trainer:
            return RedirectResponse("/auth/login", status_code=303)
        course = _own_course(db, trainer.id, course_id)
        form = await request.form()
        if form.get("status") in VALID_STATUSES:
            course.status = form["status"]
            course.has_unpublished_changes = True
            _sync_enrollment_status(db, course)
            db.commit()
            flash(request, "Course status updated.", "success")
        return RedirectResponse(f"/trainer/courses/{course_id}", status_code=303)


@router.get("/courses/{course_id}/participants", name="trainer.participants")
async def participants(request: Request, course_id: int):
    from app import render

    with SessionLocal() as db:
        trainer = _guard(request, db)
        if not trainer:
            return RedirectResponse("/auth/login", status_code=303)
        course = _own_course(db, trainer.id, course_id)
        enrollments = db.query(Enrollment).filter_by(course_id=course_id).all()
        return render(request, db, "trainer/participants.html",
                      course=course, bookings=enrollments)


# ──────────────────────────────────────────────────────────────────────────────
# Module management (Create / Edit / Delete)
# ──────────────────────────────────────────────────────────────────────────────

@router.api_route("/courses/{course_id}/modules/create", methods=["GET", "POST"], name="trainer.create_module")
async def create_module(request: Request, course_id: int):
    from app import render, flash

    with SessionLocal() as db:
        trainer = _guard(request, db)
        if not trainer:
            return RedirectResponse("/auth/login", status_code=303)
        course = _own_course(db, trainer.id, course_id)

        if request.method == "GET":
            return render(request, db, "trainer/module_form.html",
                          course=course, module=None, form={})

        form = await request.form()
        title = str(form.get("title", "")).strip()
        if not title:
            flash(request, "Module title is required.", "danger")
            return render(request, db, "trainer/module_form.html",
                          course=course, module=None, form=form)

        next_order = len(course.modules) + 1
        module = Module(
            course_id=course.id,
            title=title,
            description=str(form.get("description", "")).strip() or None,
            order=next_order,
            is_published=False,
        )
        db.add(module)
        course.has_unpublished_changes = True
        db.commit()

        # Add lecture videos if provided
        video_titles = form.getlist("video_title")
        video_urls = form.getlist("video_url")
        video_durations = form.getlist("video_duration")
        video_transcripts = form.getlist("video_transcript")
        for i, (vt, vu) in enumerate(zip(video_titles, video_urls)):
            vt, vu = vt.strip(), vu.strip()
            if vt and vu:
                try:
                    dur = int(video_durations[i]) if i < len(video_durations) else None
                except (ValueError, IndexError):
                    dur = None
                chunks = parse_timestamped_transcript(
                    video_transcripts[i] if i < len(video_transcripts) else ""
                )
                db.add(LectureVideo(module_id=module.id, title=vt, video_url=vu,
                                    duration_minutes=dur, order=i + 1,
                                    transcript_json=json.dumps(chunks) if chunks else None,
                                    transcript_status="draft_ready" if chunks else "none",
                                    is_published=False))
        db.commit()
        flash(request, "Module created successfully.", "success")
        return RedirectResponse(f"/trainer/courses/{course_id}", status_code=303)


@router.api_route(
    "/courses/{course_id}/modules/{module_id}/edit",
    methods=["GET", "POST"],
    name="trainer.edit_module",
)
async def edit_module(request: Request, course_id: int, module_id: int):
    from app import render, flash

    with SessionLocal() as db:
        trainer = _guard(request, db)
        if not trainer:
            return RedirectResponse("/auth/login", status_code=303)
        course = _own_course(db, trainer.id, course_id)
        module = db.get(Module, module_id)
        if not module or module.course_id != course_id:
            raise HTTPException(404)

        if request.method == "GET":
            return render(request, db, "trainer/module_form.html",
                          course=course, module=module, form=None)

        form = await request.form()
        title = str(form.get("title", "")).strip()
        if not title:
            flash(request, "Module title is required.", "danger")
            return render(request, db, "trainer/module_form.html",
                          course=course, module=module, form=form)
        module.title = title
        module.description = str(form.get("description", "")).strip() or None
        module.is_published = False
        course.has_unpublished_changes = True
        db.commit()
        existing_count = len(module.videos)
        video_titles = form.getlist("video_title")
        video_urls = form.getlist("video_url")
        video_durations = form.getlist("video_duration")
        video_transcripts = form.getlist("video_transcript")
        for index, (video_title, video_url) in enumerate(zip(video_titles, video_urls)):
            video_title, video_url = video_title.strip(), video_url.strip()
            if not video_title or not video_url:
                continue
            try:
                duration = int(video_durations[index])
            except (ValueError, IndexError, TypeError):
                duration = None
            chunks = parse_timestamped_transcript(
                video_transcripts[index] if index < len(video_transcripts) else ""
            )
            db.add(LectureVideo(
                module_id=module.id,
                title=video_title,
                video_url=video_url,
                duration_minutes=duration,
                transcript_json=json.dumps(chunks) if chunks else None,
                order=existing_count + index + 1,
                is_published=False,
                transcript_status="draft_ready" if chunks else "none",
            ))
        db.commit()
        flash(request, "Module updated.", "success")
        return RedirectResponse(f"/trainer/courses/{course_id}", status_code=303)


@router.post(
    "/courses/{course_id}/modules/{module_id}/delete",
    name="trainer.delete_module",
)
async def delete_module(request: Request, course_id: int, module_id: int):
    from app import flash

    with SessionLocal() as db:
        trainer = _guard(request, db)
        if not trainer:
            return RedirectResponse("/auth/login", status_code=303)
        _own_course(db, trainer.id, course_id)
        module = db.get(Module, module_id)
        if module and module.course_id == course_id:
            db.delete(module)
            db.commit()
        flash(request, "Module deleted.", "success")
        return RedirectResponse(f"/trainer/courses/{course_id}", status_code=303)
