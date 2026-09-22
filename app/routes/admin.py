"""
Admin routes — platform management (courses, trainers, trainees, bookings).
All routes require role='admin'.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import or_

from app.extensions import SessionLocal
from app.models import Course, Enrollment, User

router = APIRouter()

VALID_STATUSES = ("Registered", "In Progress", "Completed")


def _guard(request: Request, db) -> User | None:
    """Return the admin user or None (triggers login redirect)."""
    from app.decorators import current_account

    user = current_account(request, db)
    if user and user.role == "admin" and user.is_active:
        return user
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Dashboard
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/dashboard", name="admin.dashboard")
async def dashboard(request: Request):
    from app import render

    with SessionLocal() as db:
        if not _guard(request, db):
            return RedirectResponse("/auth/login", status_code=303)

        stats = {
            "total_courses": db.query(Course).count(),
            "total_trainees": db.query(User).filter_by(role="trainee").count(),
            "total_trainers": db.query(User).filter_by(role="trainer").count(),
            "total_bookings": db.query(Enrollment).count(),
            "pending_trainers": db.query(User).filter_by(role="trainer", is_approved=False).count(),
            "active_bookings": db.query(Enrollment).filter_by(status="Enrolled").count(),
            "in_progress_courses": db.query(Course).filter_by(status="In Progress").count(),
        }
        recent = db.query(Enrollment).order_by(Enrollment.enrolled_at.desc()).limit(5).all()
        return render(request, db, "admin/dashboard.html", stats=stats, recent_bookings=recent)


# ──────────────────────────────────────────────────────────────────────────────
# Course management
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/courses", name="admin.courses")
async def courses(request: Request):
    from app import render

    with SessionLocal() as db:
        if not _guard(request, db):
            return RedirectResponse("/auth/login", status_code=303)
        q = request.query_params.get("q", "").strip()
        query = db.query(Course)
        if q:
            filters = [Course.name.ilike(f"%{q}%"), Course.location.ilike(f"%{q}%")]
            if q.isdigit():
                filters.append(Course.id == int(q))
            query = query.filter(or_(*filters))
        return render(request, db, "admin/courses.html",
                      courses=query.order_by(Course.created_at.desc()).all(), q=q)


async def _parse_course_form(request: Request) -> tuple[list[str], dict, object]:
    form = await request.form()
    errors: list[str] = []
    data = {k: str(form.get(k, "")).strip()
            for k in ("name", "location", "difficulty", "duration", "description", "category")}

    if len(data["name"]) < 3:
        errors.append("Course name must be at least 3 characters.")
    if not data["location"]:
        errors.append("Location is required.")
    if data["difficulty"] not in ("Easy", "Moderate", "Hard"):
        errors.append("Please select a valid difficulty level.")

    try:
        total_slots = int(form.get("total_slots", 0))
    except (ValueError, TypeError):
        total_slots = 0
    if total_slots <= 0:
        errors.append("Total slots must be a positive number.")

    start = end = None
    try:
        start = datetime.strptime(str(form.get("start_date")), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        errors.append("Invalid start date.")
    try:
        end = datetime.strptime(str(form.get("end_date")), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        errors.append("Invalid end date.")
    if start and end and end < start:
        errors.append("End date cannot be before start date.")

    data.update(total_slots=total_slots, start_date=start, end_date=end)
    return errors, data, form


@router.api_route("/courses/create", methods=["GET", "POST"], name="admin.create_course")
async def create_course(request: Request):
    from app import render, flash

    with SessionLocal() as db:
        if not _guard(request, db):
            return RedirectResponse("/auth/login", status_code=303)
        trainers = db.query(User).filter_by(role="trainer", is_approved=True, is_active=True).all()
        if request.method == "GET":
            return render(request, db, "admin/course_form.html",
                          course=None, trainer_list=trainers, form={})

        errors, data, form = await _parse_course_form(request)
        if errors:
            for e in errors:
                flash(request, e, "danger")
            return render(request, db, "admin/course_form.html",
                          course=None, trainer_list=trainers, form=form)

        trainer_id = form.get("assigned_trainer_id")
        course = Course(
            **data,
            available_slots=data["total_slots"],
            trainer_id=int(trainer_id) if trainer_id else None,
            status="Registered",
        )
        db.add(course)
        db.commit()
        flash(request, "Course created successfully.", "success")
        return RedirectResponse("/admin/courses", status_code=303)


@router.api_route("/courses/{course_id}/edit", methods=["GET", "POST"], name="admin.edit_course")
async def edit_course(request: Request, course_id: int):
    from app import render, flash

    with SessionLocal() as db:
        if not _guard(request, db):
            return RedirectResponse("/auth/login", status_code=303)
        course = db.get(Course, course_id)
        trainers = db.query(User).filter_by(role="trainer", is_approved=True, is_active=True).all()
        if not course:
            raise HTTPException(404)
        if request.method == "GET":
            return render(request, db, "admin/course_form.html",
                          course=course, trainer_list=trainers, form=None)

        errors, data, form = await _parse_course_form(request)
        if data["total_slots"] < course.active_bookings_count():
            errors.append("Total slots cannot be less than existing active enrollments.")
        if errors:
            for e in errors:
                flash(request, e, "danger")
            return render(request, db, "admin/course_form.html",
                          course=course, trainer_list=trainers, form=form)

        diff = data["total_slots"] - course.total_slots
        for key, value in data.items():
            setattr(course, key, value)
        course.available_slots = max(0, course.available_slots + diff)
        course.trainer_id = int(form.get("assigned_trainer_id")) if form.get("assigned_trainer_id") else None
        if form.get("status") in VALID_STATUSES:
            course.status = form["status"]
            _sync_enrollment_status(db, course)
        db.commit()
        flash(request, "Course updated successfully.", "success")
        return RedirectResponse("/admin/courses", status_code=303)


@router.post("/courses/{course_id}/delete", name="admin.delete_course")
async def delete_course(request: Request, course_id: int):
    from app import flash

    with SessionLocal() as db:
        if not _guard(request, db):
            return RedirectResponse("/auth/login", status_code=303)
        course = db.get(Course, course_id)
        if course:
            db.delete(course)
            db.commit()
        flash(request, "Course deleted successfully.", "success")
        return RedirectResponse("/admin/courses", status_code=303)


# ──────────────────────────────────────────────────────────────────────────────
# Trainer management
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/trainers", name="admin.trainers_list")
async def trainers_list(request: Request):
    return await _user_list(request, "trainer", "admin/trainers.html", "trainers")


@router.post("/trainers/{trainer_id}/approve", name="admin.approve_trainer")
async def approve_trainer(request: Request, trainer_id: int):
    return await _trainer_action(request, trainer_id, approved=True)


@router.post("/trainers/{trainer_id}/reject", name="admin.reject_trainer")
async def reject_trainer(request: Request, trainer_id: int):
    return await _trainer_action(request, trainer_id, approved=False)


async def _trainer_action(request: Request, trainer_id: int, approved: bool):
    from app import flash

    with SessionLocal() as db:
        if not _guard(request, db):
            return RedirectResponse("/auth/login", status_code=303)
        trainer = db.get(User, trainer_id)
        if trainer:
            if approved:
                trainer.is_approved = True
            else:
                db.delete(trainer)
            db.commit()
        flash(request, "Trainer updated.", "success")
        return RedirectResponse("/admin/trainers", status_code=303)


# ──────────────────────────────────────────────────────────────────────────────
# Trainee management
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/trainees", name="admin.trainees_list")
async def trainees_list(request: Request):
    return await _user_list(request, "trainee", "admin/trainees.html", "trainees")


async def _user_list(request: Request, role: str, template: str, key: str):
    from app import render

    with SessionLocal() as db:
        if not _guard(request, db):
            return RedirectResponse("/auth/login", status_code=303)
        q = request.query_params.get("q", "").strip()
        query = db.query(User).filter_by(role=role)
        if q:
            filters = [User.name.ilike(f"%{q}%"), User.email.ilike(f"%{q}%")]
            if q.isdigit():
                filters.append(User.id == int(q))
            query = query.filter(or_(*filters))
        return render(request, db, template,
                      **{key: query.order_by(User.created_at.desc()).all(), "q": q})


# ──────────────────────────────────────────────────────────────────────────────
# Account toggle active
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/accounts/{account_id}/toggle-active", name="admin.toggle_active")
async def toggle_active(request: Request, account_id: int):
    with SessionLocal() as db:
        if not _guard(request, db):
            return RedirectResponse("/auth/login", status_code=303)
        user = db.get(User, account_id)
        if user and user.role != "admin":
            user.is_active = not user.is_active
            db.commit()
        return RedirectResponse(
            request.headers.get("referer", "/admin/dashboard"), status_code=303
        )


# ──────────────────────────────────────────────────────────────────────────────
# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _sync_enrollment_status(db, course: Course) -> None:
    """Cascade course status change to its enrollments."""
    if course.status == "Completed":
        for e in course.enrollments:
            if e.status == "Enrolled":
                e.status = "Completed"
    elif course.status in ("In Progress", "Registered"):
        for e in course.enrollments:
            if e.status == "Completed":
                e.status = "Enrolled"
