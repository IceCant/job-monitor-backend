import os

from fastapi import APIRouter, Depends, HTTPException, status
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.security import create_token, get_current_user, verify_password
from app.database import get_db
from app.models.user import User
from app.schemas.api import GoogleLoginRequest, LoginRequest, TokenResponse, UserOut

router = APIRouter()

DEFAULT_GOOGLE_ALLOWED_EMAILS = {"eartechboung@gmail.com"}


def _csv_env(name: str) -> set[str]:
    raw = os.getenv(name, "")
    return {part.strip().lower() for part in raw.split(",") if part.strip()}


def _google_email_aliases(email: str) -> set[str]:
    email = email.strip().lower()
    aliases = {email} if email else set()
    if email.endswith("@gmail.com"):
        aliases.add(email.removesuffix("@gmail.com") + "@googlemail.com")
    elif email.endswith("@googlemail.com"):
        aliases.add(email.removesuffix("@googlemail.com") + "@gmail.com")
    return aliases


def _allowed_google_emails() -> set[str]:
    allowed = set()
    for email in _csv_env("GOOGLE_ALLOWED_EMAILS") | DEFAULT_GOOGLE_ALLOWED_EMAILS:
        allowed.update(_google_email_aliases(email))

    admin_username = os.getenv("JOBMONITOR_ADMIN_USERNAME", "").strip().lower()
    if admin_username:
        allowed.update(_google_email_aliases(admin_username))

    return allowed


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == body.username).first()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    return TokenResponse(access_token=create_token(user), user=UserOut.model_validate(user))


@router.post("/google", response_model=TokenResponse)
def google_login(body: GoogleLoginRequest, db: Session = Depends(get_db)):
    client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    if not client_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google sign-in is not configured",
        )

    try:
        payload = google_id_token.verify_oauth2_token(
            body.id_token,
            google_requests.Request(),
            client_id,
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Google sign-in token",
        ) from None

    email = str(payload.get("email") or "").strip().lower()
    email_verified = payload.get("email_verified")
    if not email or email_verified is not True:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google email address is not verified",
        )

    if email not in _allowed_google_emails():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This Google account is not allowed",
        )

    user = db.query(User).filter(func.lower(User.username).in_(_google_email_aliases(email))).first()
    if user is None:
        user = User(
            username=email,
            password_hash="google_oauth$disabled",
            role="admin",
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    return TokenResponse(access_token=create_token(user), user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return current_user
