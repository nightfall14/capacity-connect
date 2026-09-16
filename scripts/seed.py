"""
Capacity Connect — Seed Script
================================
Populates the database with realistic demo data for instant local development.

Usage:
    python -m scripts.seed

Idempotent: running multiple times will not create duplicate data (it checks
for existing records first and only fills missing ones).

Demo credentials:
    Admin:    admin@capacityconnect.com    / Admin@123
    Trainer1: trainer1@capacityconnect.com / Trainer@123
    Trainer2: trainer2@capacityconnect.com / Trainer@123
    Trainee1: trainee1@capacityconnect.com / Trainee@123
    Trainee2: trainee2@capacityconnect.com / Trainee@123
    Trainee3: trainee3@capacityconnect.com / Trainee@123
"""

from __future__ import annotations

import sys
import os
import json

# Allow running from the project root as `python -m scripts.seed`
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from datetime import date, timedelta

from sqlalchemy import select

from app.extensions import Base, SessionLocal, engine
from app.models import (
    Assessment,
    CompetencyProfile,
    Course,
    Doubt,
    Enrollment,
    LectureVideo,
    Module,
    TelemetryLog,
    User,
    VideoEvent,
)
from config import Config
from app.services.lecture_qa_service import parse_timestamped_transcript


def run() -> None:
    # Ensure all tables exist
    import app.models  # noqa: F401 — registers metadata

    # Run column migrations for existing databases
    from sqlalchemy import inspect as sa_inspect, text as sa_text
    with engine.begin() as conn:
        tables = set(sa_inspect(engine).get_table_names())
        if "accounts" in tables:
            cols = {c["name"] for c in sa_inspect(engine).get_columns("accounts")}
            for col, defn in [("designation", "VARCHAR(120)"), ("department", "VARCHAR(120)"), ("bio", "TEXT")]:
                if col not in cols:
                    conn.exec_driver_sql(f'ALTER TABLE "accounts" ADD COLUMN "{col}" {defn}')
        if "courses" in tables:
            cols = {c["name"] for c in sa_inspect(engine).get_columns("courses")}
            for col, defn in [("category", "VARCHAR(80)"), ("thumbnail_url", "VARCHAR(300)")]:
                if col not in cols:
                    conn.exec_driver_sql(f'ALTER TABLE "courses" ADD COLUMN "{col}" {defn}')
        if "bookings" in tables:
            cols = {c["name"] for c in sa_inspect(engine).get_columns("bookings")}
            if "progress_pct" not in cols:
                conn.exec_driver_sql('ALTER TABLE "bookings" ADD COLUMN "progress_pct" REAL NOT NULL DEFAULT 0.0')
        # Migrate Booked → Enrolled status
        if "bookings" in tables:
            conn.execute(sa_text("UPDATE bookings SET status='Enrolled' WHERE status='Booked'"))

    Base.metadata.create_all(engine)

    with SessionLocal() as db:
        _seed_users(db)
        _seed_courses(db)
        _seed_modules_and_videos(db)
        _seed_demo_transcript(db)
        _seed_enrollments(db)
        _seed_assessments(db)
        _seed_doubts(db)
        _seed_telemetry(db)
        _seed_video_events(db)
        _seed_competency_profiles(db)

    print("\n✅  Seed complete!")
    print("─" * 50)
    print("Demo credentials:")
    print(f"  Admin:    {Config.ADMIN_EMAIL} / {Config.ADMIN_PASSWORD}")
    print("  Trainer1: trainer1@capacityconnect.com / Trainer@123")
    print("  Trainer2: trainer2@capacityconnect.com / Trainer@123")
    print("  Trainee1: trainee1@capacityconnect.com / Trainee@123")
    print("  Trainee2: trainee2@capacityconnect.com / Trainee@123")
    print("  Trainee3: trainee3@capacityconnect.com / Trainee@123")
    print("─" * 50)
    print(f"  Run: uvicorn app:app --reload --port 5001")


# ──────────────────────────────────────────────────────────────────────────────

def _get_or_create_user(db, *, email: str, password: str, **kwargs) -> tuple[User, bool]:
    """Return (user, created). If created=True, the user has been committed."""
    existing = db.scalar(select(User).where(User.email == email))
    if existing:
        return existing, False
    user = User(email=email, **kwargs)
    user.set_password(password)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user, True


def _seed_users(db) -> None:
    print("📦  Seeding users …")

    # Admin
    if not db.scalar(select(User).where(User.email == Config.ADMIN_EMAIL)):
        admin = User(
            name=Config.ADMIN_NAME,
            email=Config.ADMIN_EMAIL,
            role="admin",
            is_approved=True,
            is_active=True,
        )
        admin.set_password(Config.ADMIN_PASSWORD)
        db.add(admin)
        db.commit()
        print(f"  + Admin: {Config.ADMIN_EMAIL}")

    # Trainers
    trainer_data = [
        dict(name="Ramesh Kumar", email="trainer1@capacityconnect.com",
             phone="9876500001", designation="Senior Data Scientist",
             department="AI & Analytics", is_approved=True,
             password="Trainer@123"),
        dict(name="Anita Sharma", email="trainer2@capacityconnect.com",
             phone="9876500002", designation="Cloud Architect",
             department="Infrastructure", is_approved=True,
             password="Trainer@123"),
        dict(name="Vikram Singh", email="trainer3@capacityconnect.com",
             phone="9876500003", designation="Cybersecurity Lead",
             department="Security", is_approved=False,
             password="Trainer@123"),
    ]
    for td in trainer_data:
        _, created = _get_or_create_user(
            db, role="trainer", is_active=True,
            bio="Experienced industry professional.", **td,
        )
        if created:
            print(f"  + Trainer: {td['email']}")

    # Trainees
    trainee_data = [
        dict(name="Rohit Verma", email="trainee1@capacityconnect.com",
             phone="9876500011", designation="Junior Developer",
             department="Engineering", password="Trainee@123"),
        dict(name="Priya Nair", email="trainee2@capacityconnect.com",
             phone="9876500012", designation="Data Analyst",
             department="Analytics", password="Trainee@123"),
        dict(name="Arjun Mehta", email="trainee3@capacityconnect.com",
             phone="9876500013", designation="DevOps Engineer",
             department="Operations", password="Trainee@123"),
    ]
    for td in trainee_data:
        _, created = _get_or_create_user(
            db, role="trainee", is_approved=True, is_active=True, **td,
        )
        if created:
            print(f"  + Trainee: {td['email']}")


def _seed_courses(db) -> None:
    print("📚  Seeding courses …")
    today = date.today()

    trainers = db.query(User).filter_by(role="trainer", is_approved=True).all()
    if not trainers:
        print("  ⚠  No approved trainers found, skipping courses.")
        return

    t1, t2 = trainers[0], trainers[1] if len(trainers) > 1 else trainers[0]

    courses_data = [
        dict(
            name="Python for Data Science",
            description="Master Python fundamentals and apply them to real-world data analysis tasks.",
            location="Online", difficulty="Moderate", duration="8 Weeks",
            category="Data Science", total_slots=30, available_slots=22,
            trainer_id=t1.id, status="In Progress",
            start_date=today - timedelta(days=14),
            end_date=today + timedelta(days=42),
        ),
        dict(
            name="Cloud Computing with AWS",
            description="Hands-on AWS training covering EC2, S3, Lambda, RDS and best practices.",
            location="Online", difficulty="Hard", duration="10 Weeks",
            category="Cloud", total_slots=20, available_slots=15,
            trainer_id=t2.id, status="In Progress",
            start_date=today - timedelta(days=7),
            end_date=today + timedelta(days=63),
        ),
        dict(
            name="Introduction to Machine Learning",
            description="Foundational ML concepts: supervised, unsupervised, and reinforcement learning.",
            location="Online", difficulty="Moderate", duration="6 Weeks",
            category="AI/ML", total_slots=25, available_slots=25,
            trainer_id=t1.id, status="Registered",
            start_date=today + timedelta(days=30),
            end_date=today + timedelta(days=72),
        ),
        dict(
            name="Cybersecurity Fundamentals",
            description="Core concepts of network security, ethical hacking, and compliance frameworks.",
            location="Online", difficulty="Hard", duration="12 Weeks",
            category="Security", total_slots=15, available_slots=15,
            trainer_id=t2.id, status="Registered",
            start_date=today + timedelta(days=45),
            end_date=today + timedelta(days=129),
        ),
        dict(
            name="Agile & Scrum for Teams",
            description="Practical Agile methodology, sprint planning, retrospectives and Jira workflows.",
            location="Hybrid — Chennai", difficulty="Easy", duration="3 Weeks",
            category="Project Management", total_slots=40, available_slots=0,
            trainer_id=t2.id, status="Completed",
            start_date=today - timedelta(days=60),
            end_date=today - timedelta(days=39),
        ),
    ]

    for cd in courses_data:
        exists = db.scalar(select(Course).where(Course.name == cd["name"]))
        if not exists:
            db.add(Course(**cd))
            db.commit()
            print(f"  + Course: {cd['name']}")


def _seed_modules_and_videos(db) -> None:
    print("🎬  Seeding modules & videos …")

    ml_course = db.scalar(select(Course).where(Course.name == "Python for Data Science"))
    if ml_course and not ml_course.modules:
        modules_spec = [
            ("Week 1 — Python Foundations", [
                ("Python Syntax & Variables", "https://www.youtube.com/watch?v=kqtD5dpn9C8", 45),
                ("Data Structures: Lists, Dicts, Sets", "https://www.youtube.com/watch?v=W8KRzm-HUcc", 50),
            ]),
            ("Week 2 — Data Manipulation", [
                ("NumPy Arrays", "https://www.youtube.com/watch?v=QUT1VHiLmmI", 40),
                ("Pandas DataFrames", "https://www.youtube.com/watch?v=vmEHCJofslg", 55),
            ]),
            ("Week 3 — Visualization", [
                ("Matplotlib Basics", "https://www.youtube.com/watch?v=3Xc3CA655Y4", 35),
                ("Seaborn for Statistical Plots", "https://www.youtube.com/watch?v=6GUZXDef2U0", 40),
            ]),
        ]
        for order_i, (title, videos) in enumerate(modules_spec, start=1):
            mod = Module(course_id=ml_course.id, title=title, order=order_i)
            db.add(mod)
            db.commit()
            for v_order, (vt, vu, dur) in enumerate(videos, start=1):
                db.add(LectureVideo(module_id=mod.id, title=vt, video_url=vu,
                                    duration_minutes=dur, order=v_order))
            db.commit()
            print(f"  + Module: {title}")


def _seed_demo_transcript(db) -> None:
    """Trainer-authored sample transcript used by the offline lecture Q&A demo."""
    lecture = db.scalar(select(LectureVideo).order_by(LectureVideo.id))
    if not lecture or lecture.transcript_json:
        return
    raw_transcript = """[00:00] Welcome to Python syntax and variables.
[00:35] Python uses indentation to group statements into code blocks.
[01:10] A variable stores a value so that we can use it again later.
[02:00] Strings hold text, while integers hold whole numbers.
[03:05] Use the print function to display a value in the console.
[04:10] A list is an ordered collection that you can change after creating it.
[05:20] A tuple is an ordered collection that is immutable and cannot be changed.
[06:35] Dictionaries store values under named keys for quick lookup.
[08:00] Use a for loop when you need to repeat work for every item in a list.
[09:20] An if statement lets your program choose an action based on a condition.
[10:45] Functions package reusable steps behind a descriptive name.
[12:15] Review the difference between mutable lists and immutable tuples before continuing."""
    lecture.transcript_json = json.dumps(parse_timestamped_transcript(raw_transcript))
    lecture.transcript_status = "draft_ready"
    db.commit()
    print(f"  + Manual transcript for {lecture.title}")


def _seed_enrollments(db) -> None:
    print("📋  Seeding enrollments …")
    trainees = db.query(User).filter_by(role="trainee").all()
    courses = db.query(Course).all()
    if not trainees or not courses:
        return

    enroll_map = [
        # (trainee email, course name, status)
        ("trainee1@capacityconnect.com", "Python for Data Science", "Enrolled"),
        ("trainee1@capacityconnect.com", "Agile & Scrum for Teams", "Completed"),
        ("trainee2@capacityconnect.com", "Cloud Computing with AWS", "Enrolled"),
        ("trainee2@capacityconnect.com", "Python for Data Science", "Enrolled"),
        ("trainee3@capacityconnect.com", "Agile & Scrum for Teams", "Completed"),
        ("trainee3@capacityconnect.com", "Cloud Computing with AWS", "Enrolled"),
    ]
    trainee_map = {u.email: u for u in trainees}
    course_map = {c.name: c for c in courses}

    for te, cn, status in enroll_map:
        learner = trainee_map.get(te)
        course = course_map.get(cn)
        if not learner or not course:
            continue
        exists = db.scalar(
            select(Enrollment)
            .where(Enrollment.learner_id == learner.id, Enrollment.course_id == course.id)
        )
        if not exists:
            db.add(Enrollment(learner_id=learner.id, course_id=course.id, status=status))
            db.commit()
            print(f"  + Enrollment: {te} → {cn} [{status}]")


def _seed_assessments(db) -> None:
    print("📝  Seeding assessments …")
    t1 = db.scalar(select(User).where(User.email == "trainee1@capacityconnect.com"))
    py_course = db.scalar(select(Course).where(Course.name == "Python for Data Science"))
    if t1 and py_course:
        exists = db.scalar(
            select(Assessment)
            .where(Assessment.learner_id == t1.id, Assessment.course_id == py_course.id)
        )
        if not exists:
            db.add(Assessment(
                course_id=py_course.id, learner_id=t1.id,
                title="Week 1 Quiz — Python Basics",
                score=82.0, max_score=100.0,
                feedback="Good understanding of data structures. Review list comprehension.",
            ))
            db.commit()
            print("  + Assessment for trainee1 in Python for Data Science")
    t2 = db.scalar(select(User).where(User.email == "trainee2@capacityconnect.com"))
    if t2 and py_course and not db.scalar(
        select(Assessment).where(Assessment.learner_id == t2.id, Assessment.course_id == py_course.id)
    ):
        db.add(Assessment(
            course_id=py_course.id, learner_id=t2.id,
            title="Week 1 Quiz — Python Basics", score=64.0, max_score=100.0,
            feedback="Review mutable and immutable data structures.",
        ))
        db.commit()
        print("  + Assessment for trainee2 in Python for Data Science")
    cloud_course = db.scalar(select(Course).where(Course.name == "Cloud Computing with AWS"))
    for email, score in (("trainee2@capacityconnect.com", 78.0), ("trainee3@capacityconnect.com", 52.0)):
        learner = db.scalar(select(User).where(User.email == email))
        if learner and cloud_course and not db.scalar(
            select(Assessment).where(
                Assessment.learner_id == learner.id, Assessment.course_id == cloud_course.id
            )
        ):
            db.add(Assessment(
                course_id=cloud_course.id, learner_id=learner.id,
                title="Cloud Foundations Checkpoint", score=score, max_score=100.0,
                feedback="Seeded readiness input.",
            ))
            db.commit()
            print(f"  + Cloud assessment for {email}")


def _seed_doubts(db) -> None:
    print("❓  Seeding doubts …")
    t1 = db.scalar(select(User).where(User.email == "trainee1@capacityconnect.com"))
    py_course = db.scalar(select(Course).where(Course.name == "Python for Data Science"))
    if t1 and py_course:
        if not db.scalar(select(Doubt).where(Doubt.learner_id == t1.id)):
            db.add(Doubt(
                course_id=py_course.id, learner_id=t1.id,
                question="What is the difference between a list and a tuple in Python?",
                answer="Lists are mutable (changeable) while tuples are immutable. "
                       "Use tuples for fixed collections.",
                is_resolved=True,
            ))
            db.commit()
            print("  + Doubt for trainee1")


def _seed_telemetry(db) -> None:
    print("📡  Seeding telemetry …")
    t1 = db.scalar(select(User).where(User.email == "trainee1@capacityconnect.com"))
    py_course = db.scalar(select(Course).where(Course.name == "Python for Data Science"))
    if t1 and py_course and not db.scalar(select(TelemetryLog).where(TelemetryLog.user_id == t1.id)):
        logs = [
            TelemetryLog(user_id=t1.id, event_type="course_view", entity_type="course", entity_id=py_course.id),
            TelemetryLog(user_id=t1.id, event_type="video_watch", entity_type="video", entity_id=1,
                         metadata_json='{"percent_watched": 85}'),
            TelemetryLog(user_id=t1.id, event_type="quiz_submit", entity_type="assessment", entity_id=1,
                         metadata_json='{"score": 82}'),
        ]
        db.add_all(logs)
        db.commit()
        print(f"  + {len(logs)} telemetry events for trainee1")


def _seed_video_events(db) -> None:
    """Create a visible, realistic confusion spike for the first demo lecture."""
    print("🌡️  Seeding video events …")
    lecture = db.scalar(select(LectureVideo).order_by(LectureVideo.id))
    trainees = db.query(User).filter_by(role="trainee", is_active=True).all()
    if not lecture or not trainees:
        return
    if db.scalar(select(VideoEvent).where(VideoEvent.lecture_id == lecture.id)):
        return

    # Several learners pause and replay the explanation near 10:20, with a
    # smaller bump around 18:40.  Timestamps land in 10-second heatmap buckets.
    event_spec = [
        (0, "pause", 618), (0, "rewind", 622),
        (1, "pause", 621), (1, "rewind", 625),
        (2, "pause", 626), (2, "rewind", 628),
        (0, "pause", 1122), (1, "rewind", 1126), (2, "pause", 1128),
    ]
    db.add_all([
        VideoEvent(
            lecture_id=lecture.id,
            account_id=trainees[trainee_index % len(trainees)].id,
            event_type=event_type,
            video_timestamp_seconds=timestamp,
        )
        for trainee_index, event_type, timestamp in event_spec
    ])
    db.commit()
    print(f"  + {len(event_spec)} confusion signals for {lecture.title}")


def _seed_competency_profiles(db) -> None:
    print("🎓  Seeding competency profiles …")
    profiles = [
        dict(
            email="trainer1@capacityconnect.com",
            skills="Python, Pandas, Scikit-learn, TensorFlow, SQL",
            qualifications="M.Sc. Data Science, IIT Madras",
            certifications="Google Professional Data Engineer, AWS Certified ML Specialty",
            linkedin_url="https://linkedin.com/in/rameshkumar-ds",
        ),
        dict(
            email="trainer2@capacityconnect.com",
            skills="AWS, Terraform, Kubernetes, Docker, Linux",
            qualifications="B.Tech Computer Science, NIT Trichy",
            certifications="AWS Solutions Architect Professional, CKA",
            linkedin_url="https://linkedin.com/in/anitasharma-cloud",
        ),
        dict(
            email="trainee1@capacityconnect.com",
            skills="Python, Excel, SQL",
            qualifications="B.Tech Information Technology",
            certifications="",
        ),
    ]
    users = {u.email: u for u in db.query(User).all()}
    for pd in profiles:
        user = users.get(pd.pop("email"))
        if user and not user.competency_profile:
            db.add(CompetencyProfile(user_id=user.id, **pd))
            db.commit()
            print(f"  + CompetencyProfile for {user.email}")


if __name__ == "__main__":
    run()
