"""Canonical per-course trainee readiness scoring."""

from __future__ import annotations

from sqlalchemy import func

from app.models import Assessment, Enrollment


def readiness_score_for_course(db, trainee_id: int, course_id: int) -> int:
    """Score readiness from course progress (60%) and assessments (40%)."""
    enrollment = db.query(Enrollment).filter(
        Enrollment.user_id == trainee_id,
        Enrollment.course_id == course_id,
    ).first()
    progress = min(100.0, max(0.0, float(enrollment.progress_percentage or 0))) if enrollment else 0.0
    assessment_average = db.query(func.avg(Assessment.score / Assessment.max_score * 100)).filter(
        Assessment.learner_id == trainee_id,
        Assessment.course_id == course_id,
        Assessment.score.is_not(None),
        Assessment.max_score > 0,
    ).scalar()
    assessment_score = min(100.0, max(0.0, float(assessment_average or 0)))
    return round(progress * 0.6 + assessment_score * 0.4)
