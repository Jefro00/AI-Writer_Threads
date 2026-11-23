"""Shared admin authentication (HTTP Basic)."""
from __future__ import annotations

import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.config import settings

security = HTTPBasic()


def require_admin(credentials: HTTPBasicCredentials = Depends(security)) -> HTTPBasicCredentials:
    user_ok = secrets.compare_digest(credentials.username, settings.admin_username)
    pass_ok = bool(settings.admin_password) and secrets.compare_digest(
        credentials.password, settings.admin_password
    )
    if not (user_ok and pass_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials
