"""Authentication helpers shared by FastAPI routes."""

from fastapi import HTTPException, Request

from app.models import Account


def current_account(request: Request, db) -> Account | None:
    account_id = request.session.get("account_id")
    return db.get(Account, account_id) if account_id else None


def require_account(request: Request, db, *roles: str) -> Account:
    account = current_account(request, db)
    if account is None or not account.is_active:
        raise HTTPException(status_code=401, detail="Please log in to continue.")
    if roles and account.role not in roles:
        raise HTTPException(status_code=403, detail="You do not have permission to view this page.")
    if account.role == "trainer" and not account.is_approved:
        raise HTTPException(status_code=403, detail="Your trainer account is awaiting approval.")
    return account
