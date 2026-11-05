"""Paths owned by the scoring, review and report work, which is not built yet.

They are listed so the UI can code against the paths today. Each answers 501 in the standard
error shape until its owner replaces it. Delete a line here when its real endpoint lands.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import CurrentUser, require_role
from app.schemas.enums import Role

router = APIRouter(prefix="/api/v1", tags=["planned (not built)"])

admin_only = require_role(Role.ADMIN)
integration_user = require_role(Role.INTEGRATOR, Role.ADMIN)


def _not_built() -> HTTPException:
    return HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "planned, not built yet")


@router.get("/sessions/{session_id}/assessment")
def get_assessment(session_id: UUID, _: CurrentUser = Depends(admin_only)):
    raise _not_built()


@router.get("/admin/review-queue")
def review_queue(_: CurrentUser = Depends(admin_only)):
    raise _not_built()


@router.post("/admin/sessions/{session_id}/review")
def review_assessment(session_id: UUID, _: CurrentUser = Depends(admin_only)):
    raise _not_built()


@router.post("/admin/sessions/{session_id}/rescore")
def rescore_assessment(session_id: UUID, _: CurrentUser = Depends(admin_only)):
    raise _not_built()


@router.get("/admin/sessions/{session_id}/report")
def get_report(session_id: UUID, _: CurrentUser = Depends(admin_only)):
    raise _not_built()


@router.get("/integration/signals")
def integration_signals(_: CurrentUser = Depends(integration_user)):
    raise _not_built()
