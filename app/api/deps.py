"""Dev-only fake login. Real login (an identity provider) is parked; see plan section 6.

Send `X-Dev-User: <name>`, `X-Dev-Role: trainee|admin|integrator`, and for trainees
`X-Dev-Trainee-Id: <id>`. Every endpoint should already use `require_role`, so plugging in real
login later only replaces `current_user`.
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
    # Stable identity key for trainees; display name for admin actors.
    user_ref: str
    role: Role
    display_name: str
    trainee_id: str | None = None


def current_user(
    x_dev_user: str | None = Header(default=None),
    x_dev_role: str | None = Header(default=None),
    x_dev_trainee_id: str | None = Header(default=None),
) -> CurrentUser:
    settings = get_settings()
    if not settings.dev_auth_enabled:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "login is not configured yet")
    if not x_dev_user or not x_dev_role:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing X-Dev-User / X-Dev-Role")
    try:
        role = Role(x_dev_role)
    except ValueError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unknown role") from None

    display_name = x_dev_user.strip()
    if not display_name:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "name must not be blank")
    if role == Role.TRAINEE:
        trainee_id = x_dev_trainee_id.strip() if x_dev_trainee_id else ""
        if not trainee_id and settings.env == "local" and settings.trainee_db_url is None:
            trainee_id = display_name  # local-only compatibility for the retired UI/test client
        if not trainee_id or len(trainee_id) > 64:
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED, "a trainee must provide a valid X-Dev-Trainee-Id"
            )
        return CurrentUser(
            user_ref=trainee_id,
            role=role,
            display_name=display_name,
            trainee_id=trainee_id,
        )
    return CurrentUser(user_ref=display_name, role=role, display_name=display_name)


def require_role(*allowed: Role):
    def dependency(user: CurrentUser = Depends(current_user)) -> CurrentUser:
        if user.role not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "role not allowed")
        return user

    return dependency


def can_see(
    user: CurrentUser, owner_ref: str, owner_trainee_id: str | None = None
) -> bool:
    """Trainees see rows with their ID; admins see everything."""
    return user.role == Role.ADMIN or (
        user.trainee_id is not None and user.trainee_id == owner_trainee_id
    )


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
