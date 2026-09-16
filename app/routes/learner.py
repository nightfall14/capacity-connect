"""Database-backed trainee dashboard, enrolments, doubts, and profile pages."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from app.extensions import SessionLocal
from app.models import Course, Enrollment, User

router = APIRouter()


def _current_trainee(request: Request, db) -> User | None:
    from app.decorators import current_account

    user = current_account(request, db)
    if user and user.role == "trainee" and user.is_active:
        return user
    return None


def _login_redirect(request: Request, db):
    user = _current_trainee(request, db)
    return user, None if user else RedirectResponse("/auth/login", status_code=303)


@router.get("/learner/dashboard", name="learner.dashboard")
async def dashboard(request: Request):
    from app import render

    with SessionLocal() as db:
        user, redirect = _login_redirect(request, db)
        if redirect:
            return redirect
        query = request.query_params.get("q", "").strip()
        enrollments = (
            db.query(Enrollment)
            .filter(
                Enrollment.user_id == user.id,
                Enrollment.status.in_(("active", "Enrolled")),
            )
            .order_by(Enrollment.enrolled_at.desc())
            .all()
        )
        courses_query = db.query(Course).filter(Course.is_published.is_(True))
        if query:
            courses_query = courses_query.filter(
                Course.title.ilike(f"%{query}%")
                | Course.description.ilike(f"%{query}%")
            )
        courses = courses_query.order_by(Course.created_at.desc()).all()
        return render(
            request,
            db,
            "learner/dashboard.html",
            enrollments=enrollments,
            courses=courses,
            query=query,
        )


@router.get("/learner/my-courses", name="learner.my_courses")
async def my_courses(request: Request):
    from app import render

    with SessionLocal() as db:
        user, redirect = _login_redirect(request, db)
        if redirect:
            return redirect
        enrollments = (
            db.query(Enrollment)
            .filter(Enrollment.user_id == user.id)
            .order_by(Enrollment.enrolled_at.desc())
            .all()
        )
        return render(request, db, "learner/my_courses.html", enrollments=enrollments)


@router.get("/learner/doubts", name="learner.doubts")
async def doubts(request: Request):
    from app import render

    with SessionLocal() as db:
        user, redirect = _login_redirect(request, db)
        if redirect:
            return redirect
        return render(request, db, "learner/doubts.html", doubts=list(user.doubts_asked))


@router.get("/learner/profile", name="learner.profile")
async def profile(request: Request):
    from app import render

    with SessionLocal() as db:
        user, redirect = _login_redirect(request, db)
        if redirect:
            return redirect
        enrollments = (
            db.query(Enrollment)
            .filter(Enrollment.user_id == user.id)
            .order_by(Enrollment.enrolled_at.desc())
            .all()
        )
        progress_values = [
            float(enrollment.progress_percentage or 0)
            for enrollment in enrollments
        ]
        return render(
            request,
            db,
            "learner/profile.html",
            user=user,
            enrollments=enrollments,
            enrolled_count=len(enrollments),
            completed_count=sum(
                enrollment.status in ("completed", "Completed")
                for enrollment in enrollments
            ),
            average_progress=(
                round(sum(progress_values) / len(progress_values), 1)
                if progress_values else 0
            ),
        )


@router.get("/readiness", name="readiness.profile")
async def readiness_profile(request: Request):
    return await profile(request)
