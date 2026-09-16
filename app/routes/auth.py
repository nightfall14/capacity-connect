"""Authentication routes: register, login, logout."""

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from app.extensions import SessionLocal
from app.models import User

router = APIRouter()


@router.get("/register/{role}", name="auth.register")
async def register_get(request: Request, role: str):
    from app import render

    with SessionLocal() as db:
        if role not in ("trainer", "trainee"):
            return RedirectResponse("/", status_code=303)
        return render(request, db, "auth/register.html", role=role, form={})


@router.post("/register/{role}", name="auth.register_post")
async def register_post(request: Request, role: str):
    from app import render, flash

    with SessionLocal() as db:
        form = await request.form()
        name = str(form.get("name", "")).strip()
        email = str(form.get("email", "")).strip().lower()
        password = str(form.get("password", ""))
        confirm = str(form.get("confirm_password", ""))
        phone = str(form.get("phone", "")).strip()

        errors: list[str] = []
        if len(name) < 3:
            errors.append("Name must be at least 3 characters long.")
        if "@" not in email or "." not in email:
            errors.append("Please provide a valid email address.")
        if len(password) < 6:
            errors.append("Password must be at least 6 characters long.")
        if password != confirm:
            errors.append("Password and Confirm Password do not match.")
        if db.scalar(select(User).where(User.email == email)):
            errors.append("An account with this email already exists.")
        if role not in ("trainer", "trainee"):
            errors.append("Invalid registration type.")

        if errors:
            for error in errors:
                flash(request, error, "danger")
            return render(request, db, "auth/register.html", role=role, form=form)

        user = User(
            name=name, email=email, phone=phone, role=role,
            is_approved=(role == "trainee"),   # trainers require admin approval
            is_active=True,
        )
        user.set_password(password)
        db.add(user)
        db.commit()
        flash(request, "Registration successful! Please log in.", "success")
        return RedirectResponse("/auth/login", status_code=303)


@router.api_route("/login", methods=["GET", "POST"], name="auth.login")
async def login(request: Request):
    from app import render, flash, dashboard_url

    with SessionLocal() as db:
        if request.method == "GET":
            return render(request, db, "auth/login.html")

        form = await request.form()
        email = str(form.get("email", "")).strip().lower()
        password = str(form.get("password", ""))

        user = db.scalar(select(User).where(User.email == email))
        if not user or not user.check_password(password):
            flash(request, "Invalid email or password.", "danger")
            return render(request, db, "auth/login.html")
        if not user.is_active:
            flash(request, "Your account has been deactivated. Contact an administrator.", "danger")
            return render(request, db, "auth/login.html")
        if user.role == "trainer" and not user.is_approved:
            flash(request, "Your trainer account is still pending administrator approval.", "warning")
            return render(request, db, "auth/login.html")

        request.session.clear()
        request.session.update({
            "account_id": user.id,
            "role": user.role,
            "name": user.name,
            # SessionMiddleware persists this signed session for seven days.
            "permanent": True,
        })
        # Starlette's SessionMiddleware uses the permanent marker with the
        # configured seven-day max_age to persist this session across reloads.
        request.session["permanent"] = True
        flash(request, f"Welcome back, {user.name}!", "success")
        return RedirectResponse(dashboard_url(user.role), status_code=303)


@router.get("/logout", name="auth.logout")
async def logout(request: Request):
    from app import flash

    request.session.clear()
    flash(request, "You have been logged out.", "info")
    return RedirectResponse("/auth/login", status_code=303)
