from __future__ import annotations

import hashlib
import secrets
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from .database import connect, row_to_dict


router = APIRouter(prefix="/auth", tags=["auth"])
security = HTTPBearer(auto_error=False)
CurrentUser = dict[str, Any]
PASSWORD_ITERATIONS = 260_000


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    username: str = Field(min_length=2, max_length=40)
    password: str = Field(min_length=8, max_length=200)
    display_name: str = Field(min_length=1, max_length=80)


class LoginRequest(BaseModel):
    identifier: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=200)


@router.post("/register")
def register(payload: RegisterRequest) -> dict[str, Any]:
    email = _normalize_email(payload.email)
    username = payload.username.strip()
    display_name = payload.display_name.strip()
    if not username:
        raise HTTPException(status_code=400, detail="username is required")
    if not display_name:
        raise HTTPException(status_code=400, detail="display_name is required")

    password_hash = _hash_password(payload.password)
    try:
        with connect() as db:
            cursor = db.execute(
                """
                INSERT INTO users (email, username, display_name, password_hash)
                VALUES (?, ?, ?, ?)
                """,
                (
                    email,
                    username,
                    display_name,
                    password_hash,
                ),
            )
            user_id = int(cursor.lastrowid)
            token = _create_session(db, user_id)
            db.commit()
            user = _get_user_by_id(db, user_id)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Email or username already exists") from exc

    return {
        "access_token": token,
        "token_type": "bearer",
        "user": _public_user(user),
    }


@router.post("/login")
def login(payload: LoginRequest) -> dict[str, Any]:
    with connect() as db:
        user = row_to_dict(
            db.execute(
                """
                SELECT *
                FROM users
                WHERE lower(email) = lower(?) OR username = ?
                """,
                (payload.identifier, payload.identifier),
            ).fetchone()
        )
        if user is None or not user.get("password_hash"):
            raise HTTPException(status_code=401, detail="Invalid credentials")
        if not _verify_password(payload.password, user["password_hash"]):
            raise HTTPException(status_code=401, detail="Invalid credentials")
        if user.get("status") != "active":
            raise HTTPException(status_code=403, detail="User is not active")

        token = _create_session(db, int(user["id"]))
        db.commit()

    return {
        "access_token": token,
        "token_type": "bearer",
        "user": _public_user(user),
    }


@router.post("/logout")
def logout(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict[str, str]:
    if credentials is None:
        return {"status": "ok"}

    token_hash = _hash_token(credentials.credentials)
    with connect() as db:
        db.execute(
            """
            UPDATE user_sessions
            SET revoked_at = CURRENT_TIMESTAMP
            WHERE token_hash = ? AND revoked_at IS NULL
            """,
            (token_hash,),
        )
        db.commit()
    return {"status": "ok"}


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> CurrentUser:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    token_hash = _hash_token(credentials.credentials)
    with connect() as db:
        user = row_to_dict(
            db.execute(
                """
                SELECT users.*
                FROM user_sessions
                JOIN users ON users.id = user_sessions.user_id
                WHERE user_sessions.token_hash = ?
                    AND user_sessions.revoked_at IS NULL
                    AND users.status = 'active'
                """,
                (token_hash,),
            ).fetchone()
        )
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return user


@router.get("/me")
def me(current_user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    return {"user": _public_user(current_user)}


def _create_session(db: sqlite3.Connection, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    db.execute(
        """
        INSERT INTO user_sessions (user_id, token_hash)
        VALUES (?, ?)
        """,
        (user_id, _hash_token(token)),
    )
    return token


def _get_user_by_id(db: sqlite3.Connection, user_id: int) -> CurrentUser:
    user = row_to_dict(
        db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    )
    if user is None:
        raise RuntimeError(f"Created user could not be loaded: {user_id}")
    return user


def _public_user(user: CurrentUser) -> dict[str, Any]:
    return {
        "id": user["id"],
        "email": user["email"],
        "username": user["username"],
        "display_name": user["display_name"],
        "avatar_path": user.get("avatar_path"),
        "role": user.get("role"),
        "status": user.get("status"),
        "created_at": user.get("created_at"),
    }


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_ITERATIONS,
    )
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}"


def _verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations_text, salt_hex, digest_hex = password_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_text)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except (ValueError, TypeError):
        return False

    actual = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return secrets.compare_digest(actual, expected)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _normalize_email(email: str) -> str:
    normalized = email.strip().lower()
    if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
        raise HTTPException(status_code=400, detail="Invalid email")
    return normalized
