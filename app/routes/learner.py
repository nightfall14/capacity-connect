"""Database-backed trainee dashboard, enrolments, doubts, and profile pages."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from secrets import token_hex
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.extensions import SessionLocal
from app.models import Assessment, Certificate, CompetencyProfile, Course, CourseFeedback, Enrollment, Quiz, User

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


@router.api_route("/learner/profile", methods=["GET", "POST"], name="learner.profile")
async def profile(request: Request):
    from app import flash, render

    with SessionLocal() as db:
        user, redirect = _login_redirect(request, db)
        if redirect:
            return redirect
        cp = user.competency_profile
        if not cp:
            cp = CompetencyProfile(user_id=user.id)
            db.add(cp)
            db.commit()
        if request.method == "POST":
            form = await request.form()
            cp.qualifications = str(form.get("qualifications", "")).strip() or None
            cp.certifications = str(form.get("certifications", "")).strip() or None
            cp.work_experience = str(form.get("work_experience", "")).strip() or None
            cp.interests = str(form.get("interests", "")).strip() or None
            cp.skills = str(form.get("skills", "")).strip() or None
            upload = form.get("certificate_file")
            if getattr(upload, "filename", ""):
                suffix = Path(upload.filename).suffix.lower()
                if suffix not in {".pdf", ".png", ".jpg", ".jpeg"}:
                    flash(request, "Certificate must be a PDF or image.", "danger")
                    return RedirectResponse("/learner/profile", status_code=303)
                folder = Path(__file__).resolve().parents[1] / "static" / "uploads" / "certificates"
                folder.mkdir(parents=True, exist_ok=True)
                filename = f"{user.id}_{token_hex(8)}{suffix}"
                (folder / filename).write_bytes(await upload.read())
                issued = str(form.get("certificate_issued_at", "")).strip()
                try: issued_at = date.fromisoformat(issued) if issued else None
                except ValueError: issued_at = None
                db.add(Certificate(user_id=user.id, title=str(form.get("certificate_title", "Certificate")).strip() or "Certificate", issuer=str(form.get("certificate_issuer", "")).strip() or None, file_path=f"/static/uploads/certificates/{filename}", issued_at=issued_at))
            db.commit()
            flash(request, "Profile saved.", "success")
            return RedirectResponse("/learner/profile", status_code=303)
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
        certificates = sorted(
            user.certificates,
            key=lambda certificate: certificate.issued_at or date.min,
            reverse=True,
        )
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
            cp=cp, certificates=certificates,
        )


@router.get("/profiles/{trainee_id}", name="learner.profile_view")
async def profile_view(request: Request, trainee_id: int):
    from app import render
    from app.decorators import current_account
    with SessionLocal() as db:
        viewer = current_account(request, db)
        trainee = db.get(User, trainee_id)
        if (
            not viewer
            or not viewer.is_active
            or viewer.role not in {"trainer", "admin"}
            or not trainee
            or trainee.role != "trainee"
        ):
            raise HTTPException(403)
        certificates = sorted(
            trainee.certificates,
            key=lambda certificate: certificate.issued_at or date.min,
            reverse=True,
        )
        return render(
            request,
            db,
            "learner/profile_view.html",
            trainee=trainee,
            cp=trainee.competency_profile,
            certificates=certificates,
        )


@router.api_route("/courses/{course_id}/quizzes/{quiz_id}", methods=["GET", "POST"], name="learner.take_quiz")
async def take_quiz(request: Request, course_id: int, quiz_id: int):
    from app import flash, render
    with SessionLocal() as db:
        user, redirect = _login_redirect(request, db)
        if redirect: return redirect
        quiz = db.get(Quiz, quiz_id)
        enrolled = db.query(Enrollment).filter_by(user_id=user.id, course_id=course_id).first()
        if not quiz or quiz.course_id != course_id or not enrolled: raise HTTPException(404)
        if request.method == "POST":
            form = await request.form()
            total = len(quiz.questions)
            correct = sum(str(form.get(f"question_{q.id}", "")).upper() == q.correct_option.upper() for q in quiz.questions)
            score = round(correct / total * 100, 2) if total else 0.0
            db.add(Assessment(course_id=course_id, learner_id=user.id, title=quiz.title, score=score, max_score=100, feedback=f"{correct}/{total} correct"))
            db.commit(); flash(request, f"Quiz submitted: {correct}/{total} correct ({score}%).", "success")
            return RedirectResponse(f"/courses/{course_id}/quizzes/{quiz_id}", status_code=303)
        return render(request, db, "learner/take_quiz.html", quiz=quiz, course=quiz.course)


@router.post("/courses/{course_id}/feedback", name="learner.course_feedback")
async def course_feedback(request: Request, course_id: int):
    from app import flash
    with SessionLocal() as db:
        user, redirect = _login_redirect(request, db)
        if redirect: return redirect
        enrollment = db.query(Enrollment).filter_by(user_id=user.id, course_id=course_id).first()
        form = await request.form()
        try: rating = int(form.get("rating", 0))
        except (TypeError, ValueError): rating = 0
        if not enrollment or (str(enrollment.status).lower() not in {"completed", "complete"} and float(enrollment.progress_percentage or 0) < 100) or rating not in range(1, 6):
            flash(request, "Feedback is available after course completion and needs a 1–5 rating.", "danger")
        else:
            db.add(CourseFeedback(course_id=course_id, learner_id=user.id, rating=rating, comment=str(form.get("comment", "")).strip() or None)); db.commit(); flash(request, "Thank you for your feedback.", "success")
        return RedirectResponse("/learner/my-courses", status_code=303)


@router.get("/readiness", name="readiness.profile")
async def readiness_profile(request: Request):
    return await profile(request)
