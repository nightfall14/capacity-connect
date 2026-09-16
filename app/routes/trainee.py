"""
Learner (Trainee) routes — course catalog, enrollment, profile, history.
All routes require role='trainee'.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select

from app.extensions import SessionLocal
from app.models import CompetencyProfile, Course, Doubt, Enrollment, LectureVideo, User

router = APIRouter()


def _guard(request: Request, db) -> User | None:
    from app.decorators import current_account

    user = current_account(request, db)
    if user and user.role == "trainee" and user.is_active:
        return user
    return None


@router.get("/lecture/{lecture_id}", name="trainee.lecture", response_class=HTMLResponse)
async def lecture(request: Request, lecture_id: int):
    from app import render

    with SessionLocal() as db:
        learner = _guard(request, db)
        if not learner:
            return RedirectResponse("/auth/login", status_code=303)
        video = db.get(LectureVideo, lecture_id)
        if not video:
            raise HTTPException(404)
        return render(request, db, "lecture.html", lecture=video, course=video.module.course)


@router.post("/lecture/{lecture_id}/doubt", name="trainee.lecture_doubt")
async def lecture_doubt(request: Request, lecture_id: int):
    from app import flash

    with SessionLocal() as db:
        learner = _guard(request, db)
        if not learner:
            return RedirectResponse("/auth/login", status_code=303)
        video = db.get(LectureVideo, lecture_id)
        if not video:
            raise HTTPException(404)
        form = await request.form()
        question = str(form.get("question", "")).strip()
        if not question:
            flash(request, "Please enter a question.", "danger")
            return RedirectResponse(f"/trainee/lecture/{lecture_id}", status_code=303)
        from app.services.video_service import transcript_match
        match = transcript_match(question)
        try:
            video_timestamp = (
                float(form["video_timestamp_seconds"])
                if form.get("video_timestamp_seconds") else None
            )
        except (TypeError, ValueError):
            video_timestamp = None
        doubt = Doubt(
            course_id=video.module.course_id, learner_id=learner.id,
            question=question, answer=match["answer"],
            is_anonymous=str(form.get("anonymous", "")).lower() in {"1", "true", "on", "yes"},
            video_timestamp_seconds=video_timestamp,
        )
        db.add(doubt)
        db.commit()
        return {
            "answer": match["answer"],
            "target_seconds": match["target_seconds"],
            "jump_label": match["jump_label"],
        }


def _grouped_by_status(db, learner_id: int) -> dict[str, list[Enrollment]]:
    grouped: dict[str, list] = {"Registered": [], "In Progress": [], "Completed": []}
    enrollments = (
        db.query(Enrollment)
        .filter_by(learner_id=learner_id)
        .join(Course, Course.id == Enrollment.course_id)
        .order_by(Enrollment.enrolled_at.desc())
        .all()
    )
    for enrollment in enrollments:
        status = enrollment.course.status if enrollment.course else "Registered"
        if status in grouped:
            grouped[status].append(enrollment)
    return grouped


# ──────────────────────────────────────────────────────────────────────────────
# Dashboard
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/dashboard", name="trainee.dashboard")
async def dashboard(request: Request):
    from app import render

    with SessionLocal() as db:
        learner = _guard(request, db)
        if not learner:
            return RedirectResponse("/auth/login", status_code=303)

        recent = (
            db.query(Enrollment)
            .filter_by(learner_id=learner.id)
            .order_by(Enrollment.enrolled_at.desc())
            .limit(5)
            .all()
        )
        grouped = _grouped_by_status(db, learner.id)
        stats = {
            "active_bookings": db.query(Enrollment)
                .filter_by(learner_id=learner.id, status="Enrolled").count(),
            "completed_courses": db.query(Enrollment)
                .filter_by(learner_id=learner.id, status="Completed").count(),
            "in_progress_courses": len(grouped["In Progress"]),
        }
        courses = (
            db.query(Course)
            .filter(Course.status.in_(("Registered", "In Progress")))
            .order_by(Course.created_at.desc())
            .limit(6)
            .all()
        )
        return render(request, db, "trainee/dashboard.html",
                      stats=stats, recent_bookings=recent, grouped=grouped,
                      courses=courses)


# ──────────────────────────────────────────────────────────────────────────────
# Peer Rescue (JSON API)
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/peer-rescue", name="trainee.peer_rescue")
async def peer_rescue(request: Request):
    with SessionLocal() as db:
        learner = _guard(request, db)
        if not learner:
            return JSONResponse({"error": "Authentication required"}, status_code=401)
        q = request.query_params.get("q", "").strip()
        if not q:
            return JSONResponse({"peers": []})

        seen: set[int] = set()
        peers: list[dict] = []
        results = (
            db.query(User, Course)
            .join(Enrollment, Enrollment.learner_id == User.id)
            .join(Course, Course.id == Enrollment.course_id)
            .filter(
                User.id != learner.id,
                User.role == "trainee",
                User.is_active.is_(True),
                Enrollment.status == "Completed",
                Course.status == "Completed",
                Course.name.ilike(f"%{q}%"),
            )
            .order_by(Course.name, User.name)
            .all()
        )
        for user, course in results:
            if user.id in seen:
                continue
            seen.add(user.id)
            peers.append({
                "id": user.id, "name": user.name, "email": user.email,
                "phone": user.phone, "course_name": course.name, "course_id": course.id,
            })
        return JSONResponse({"peers": peers})


# ──────────────────────────────────────────────────────────────────────────────
# Course catalog
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/courses", name="trainee.browse_courses")
async def browse_courses(request: Request):
    from app import render

    with SessionLocal() as db:
        learner = _guard(request, db)
        if not learner:
            return RedirectResponse("/auth/login", status_code=303)

        location = request.query_params.get("location", "").strip()
        difficulty = request.query_params.get("difficulty", "").strip()
        category = request.query_params.get("category", "").strip()

        # Both legacy Registered courses and newly published In Progress
        # courses are visible; enrollment itself still validates availability.
        query = db.query(Course).filter(Course.status.in_(("Registered", "In Progress")))
        if location:
            query = query.filter(Course.location.ilike(f"%{location}%"))
        if difficulty:
            query = query.filter_by(difficulty=difficulty)
        if category:
            query = query.filter_by(category=category)

        enrolled_ids = {
            e.course_id
            for e in db.query(Enrollment).filter_by(learner_id=learner.id, status="Enrolled")
        }
        categories = [
            r[0] for r in db.query(Course.category).distinct().filter(Course.category.isnot(None)).all()
        ]
        return render(
            request, db, "trainee/courses.html",
            courses=query.order_by(Course.start_date).all(),
            location=location, difficulty=difficulty, category=category,
            my_booked_course_ids=enrolled_ids,
            categories=categories,
        )


@router.get("/courses/{course_id}", name="trainee.course_detail")
async def course_detail(request: Request, course_id: int):
    from app import render

    with SessionLocal() as db:
        learner = _guard(request, db)
        if not learner:
            return RedirectResponse("/auth/login", status_code=303)
        course = db.get(Course, course_id)
        if not course:
            raise HTTPException(404)
        already = (
            db.query(Enrollment)
            .filter_by(learner_id=learner.id, course_id=course_id, status="Enrolled")
            .first()
        ) is not None
        return render(request, db, "trainee/course_detail.html",
                      course=course, already_booked=already)


# ──────────────────────────────────────────────────────────────────────────────
# Enrollment (book / cancel / complete)
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/courses/{course_id}/book", name="trainee.book_course")
async def book_course(request: Request, course_id: int):
    from app import flash

    with SessionLocal() as db:
        learner = _guard(request, db)
        if not learner:
            return RedirectResponse("/auth/login", status_code=303)
        course = db.get(Course, course_id)
        already = (
            db.query(Enrollment)
            .filter_by(learner_id=learner.id, course_id=course_id, status="Enrolled")
            .first()
        )
        if (course and course.status in ("Registered", "In Progress")
                and course.available_slots > 0 and not already):
            course.available_slots -= 1
            db.add(Enrollment(learner_id=learner.id, course_id=course_id))
            db.commit()
            flash(request, "Successfully enrolled in the course!", "success")
        else:
            flash(request, "Enrollment is not available at this time.", "danger")
        return RedirectResponse("/trainee/bookings", status_code=303)


@router.post("/bookings/{booking_id}/cancel", name="trainee.cancel_booking")
async def cancel_booking(request: Request, booking_id: int):
    from app import flash

    with SessionLocal() as db:
        learner = _guard(request, db)
        if not learner:
            return RedirectResponse("/auth/login", status_code=303)
        enrollment = db.get(Enrollment, booking_id)
        if enrollment and enrollment.learner_id == learner.id and enrollment.status == "Enrolled":
            enrollment.status = "Cancelled"
            enrollment.course.available_slots = min(
                enrollment.course.total_slots,
                enrollment.course.available_slots + 1,
            )
            db.commit()
            flash(request, "Enrollment cancelled successfully.", "success")
        return RedirectResponse("/trainee/bookings", status_code=303)


@router.post("/bookings/{booking_id}/complete", name="trainee.complete_booking")
async def complete_booking(request: Request, booking_id: int):
    from app import flash
    from app.routes.admin import _sync_enrollment_status

    with SessionLocal() as db:
        learner = _guard(request, db)
        if not learner:
            return RedirectResponse("/auth/login", status_code=303)
        enrollment = db.get(Enrollment, booking_id)
        if (enrollment and enrollment.learner_id == learner.id
                and enrollment.status == "Enrolled"):
            enrollment.status = "Completed"
            enrollment.course.status = "Completed"
            _sync_enrollment_status(db, enrollment.course)
            db.commit()
            flash(request, "Course marked as completed!", "success")
        else:
            flash(request, "This course cannot be marked as complete.", "danger")
        return RedirectResponse("/trainee/history", status_code=303)


# ──────────────────────────────────────────────────────────────────────────────
# Bookings & History pages
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/bookings", name="trainee.my_bookings")
async def my_bookings(request: Request):
    return await _booking_page(request, "trainee/bookings.html")


@router.get("/history", name="trainee.history")
async def history(request: Request):
    return await _booking_page(request, "trainee/history.html")


async def _booking_page(request: Request, template: str):
    from app import render

    with SessionLocal() as db:
        learner = _guard(request, db)
        if not learner:
            return RedirectResponse("/auth/login", status_code=303)
        enrollments = (
            db.query(Enrollment)
            .filter_by(learner_id=learner.id)
            .order_by(Enrollment.enrolled_at.desc())
            .all()
        )
        return render(request, db, template,
                      bookings=enrollments,
                      grouped=_grouped_by_status(db, learner.id))


# ──────────────────────────────────────────────────────────────────────────────
# Profile
# ──────────────────────────────────────────────────────────────────────────────

@router.api_route("/profile", methods=["GET", "POST"], name="trainee.profile")
async def profile(request: Request):
    from app import render, flash

    with SessionLocal() as db:
        learner = _guard(request, db)
        if not learner:
            return RedirectResponse("/auth/login", status_code=303)

        # Ensure competency profile exists
        cp = learner.competency_profile
        if not cp:
            cp = CompetencyProfile(user_id=learner.id)
            db.add(cp)
            db.commit()
            db.refresh(learner)
            cp = learner.competency_profile

        if request.method == "POST":
            form = await request.form()
            name = str(form.get("name", "")).strip()
            if len(name) < 3:
                flash(request, "Name must be at least 3 characters.", "danger")
                return RedirectResponse("/trainee/profile", status_code=303)

            learner.name = name
            learner.phone = str(form.get("phone", "")).strip()
            learner.designation = str(form.get("designation", "")).strip() or None
            learner.department = str(form.get("department", "")).strip() or None
            learner.bio = str(form.get("bio", "")).strip() or None

            cp.skills = str(form.get("skills", "")).strip() or None
            cp.qualifications = str(form.get("qualifications", "")).strip() or None
            cp.certifications = str(form.get("certifications", "")).strip() or None
            cp.linkedin_url = str(form.get("linkedin_url", "")).strip() or None

            if form.get("password"):
                learner.set_password(str(form["password"]))

            db.commit()
            request.session["name"] = learner.name
            flash(request, "Profile updated successfully.", "success")
            return RedirectResponse("/trainee/profile", status_code=303)

        return render(request, db, "trainee/profile.html", account=learner, cp=cp)
