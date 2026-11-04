"""Dev-only fake login. Real login (an identity provider) is parked; see plan section 6.

Send `X-Dev-User: <name>` and `X-Dev-Role: trainee|admin|integrator`. Every endpoint should
already use `require_role`, so plugging in real login later only replaces `current_user`.
"""

from collections.abc import Iterator
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import get_session
from app.llm import get_llm_client
from app.llm.base import LLMClient
from app.schemas.enums import Role


@dataclass(frozen=True)
class CurrentUser:
    user_ref: str
    role: Role


def current_user(
    x_dev_user: str | None = Header(default=None),
    x_dev_role: str | None = Header(default=None),
) -> CurrentUser:
    if not get_settings().dev_auth_enabled:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "login is not configured yet")
    if not x_dev_user or not x_dev_role:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing X-Dev-User / X-Dev-Role")
    try:
        role = Role(x_dev_role)
    except ValueError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unknown role") from None
    return CurrentUser(user_ref=x_dev_user, role=role)


def require_role(*allowed: Role):
    def dependency(user: CurrentUser = Depends(current_user)) -> CurrentUser:
        if user.role not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "role not allowed")
        return user

    return dependency


def can_see(user: CurrentUser, owner_ref: str) -> bool:
    """Trainees see only their own rows; admins see everything."""
    return user.role == Role.ADMIN or user.user_ref == owner_ref


def get_db() -> Iterator[Session]:
    """One database session per request. Tests replace this with an in-memory database."""
    yield from get_session()


def get_llm() -> LLMClient:
    """Tests replace this with a scripted FakeLLM."""
    return get_llm_client()


@dataclass(frozen=True)
class Paging:
    limit: int
    offset: int


def paging(
    limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0)
) -> Paging:
    return Paging(limit=limit, offset=offset)
