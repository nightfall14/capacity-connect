"""Main / landing page route."""

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from app.extensions import SessionLocal
from app.models import Course, User

router = APIRouter()


@router.get("/", name="main.index")
async def index(request: Request):
    from app import render, dashboard_url

    with SessionLocal() as db:
        account_id = request.session.get("account_id")
        if account_id:
            user = db.get(User, account_id)
            if user:
                return RedirectResponse(dashboard_url(user.role), status_code=303)
        courses = db.scalars(
            select(Course)
            .where(Course.status == "In Progress")
            .order_by(Course.start_date)
            .limit(6)
        ).all()
        return render(request, db, "index.html", courses=courses)
