"""Settings endpoints: the admin edits personas and scenarios; trainees list the published ones.

Every edit is a new numbered version. A draft can change; once published it never does.
"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, ValidationError
from pydantic import ConfigDict as PydanticConfigDict
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, get_db, require_role
from app.db import models as m
from app.schemas import PersonaConfig, ScenarioConfig
from app.schemas.enums import ConfigKind, ConfigStatus, Role

router = APIRouter(prefix="/api/v1", tags=["settings"])

admin_only = require_role(Role.ADMIN)
admin_or_trainee = require_role(Role.TRAINEE, Role.ADMIN)

CONFIG_MODELS = {ConfigKind.PERSONA: PersonaConfig, ConfigKind.SCENARIO: ScenarioConfig}
KEY_PATTERN = r"^[a-z0-9][a-z0-9-]{0,99}$"


class VersionOut(BaseModel):
    model_config = PydanticConfigDict(from_attributes=True)

    id: UUID
    kind: ConfigKind
    key: str
    version_no: int
    status: ConfigStatus
    config: dict
    created_at: datetime


class VersionSummary(BaseModel):
    model_config = PydanticConfigDict(from_attributes=True)

    id: UUID
    version_no: int
    status: ConfigStatus
    created_at: datetime


class KeyOut(BaseModel):
    key: str
    versions: list[VersionSummary]


class NewKey(BaseModel):
    key: str = Field(pattern=KEY_PATTERN)
    config: dict


class DraftBody(BaseModel):
    config: dict


class NewVersion(BaseModel):
    config: dict | None = None  # omitted: copy the latest version


class PublishedItem(BaseModel):
    key: str
    version_no: int
    title: str
    summary: str


def _validated(kind: ConfigKind, config: dict) -> dict:
    try:
        return CONFIG_MODELS[kind].model_validate(config).model_dump(mode="json")
    except ValidationError as exc:
        errors = [
            {"loc": [str(p) for p in e["loc"]], "msg": e["msg"]} for e in exc.errors()
        ]
        raise HTTPException(422, errors) from None


def _version(db: Session, kind: ConfigKind, key: str, version_no: int) -> m.ConfigVersion:
    row = db.scalar(
        select(m.ConfigVersion).where(
            m.ConfigVersion.kind == kind,
            m.ConfigVersion.key == key,
            m.ConfigVersion.version_no == version_no,
        )
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "version not found")
    return row


def _commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError:  # two admins saved the same version number at once
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "someone saved at the same time") from None


@router.get("/admin/config/{kind}", response_model=list[KeyOut])
def list_keys(
    kind: ConfigKind, _: CurrentUser = Depends(admin_only), db: Session = Depends(get_db)
):
    rows = db.scalars(
        select(m.ConfigVersion)
        .where(m.ConfigVersion.kind == kind)
        .order_by(m.ConfigVersion.key, m.ConfigVersion.version_no)
    ).all()
    grouped: dict[str, list[m.ConfigVersion]] = {}
    for row in rows:
        grouped.setdefault(row.key, []).append(row)
    return [KeyOut(key=k, versions=v) for k, v in grouped.items()]


@router.post("/admin/config/{kind}", response_model=VersionOut, status_code=201)
def create_key(
    kind: ConfigKind,
    body: NewKey,
    _: CurrentUser = Depends(admin_only),
    db: Session = Depends(get_db),
):
    exists = db.scalar(
        select(func.count()).select_from(m.ConfigVersion).where(
            m.ConfigVersion.kind == kind, m.ConfigVersion.key == body.key
        )
    )
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "that key already exists")
    row = m.ConfigVersion(
        kind=kind,
        key=body.key,
        version_no=1,
        status=ConfigStatus.DRAFT,
        config=_validated(kind, body.config),
    )
    db.add(row)
    _commit(db)
    return row


@router.post("/admin/config/{kind}/{key}/versions", response_model=VersionOut, status_code=201)
def new_version(
    kind: ConfigKind,
    key: str,
    body: NewVersion | None = None,
    _: CurrentUser = Depends(admin_only),
    db: Session = Depends(get_db),
):
    latest = db.scalar(
        select(m.ConfigVersion)
        .where(m.ConfigVersion.kind == kind, m.ConfigVersion.key == key)
        .order_by(m.ConfigVersion.version_no.desc())
    )
    if latest is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "key not found")
    new_config = body.config if body else None
    config = _validated(kind, new_config) if new_config is not None else latest.config
    row = m.ConfigVersion(
        kind=kind,
        key=key,
        version_no=latest.version_no + 1,
        status=ConfigStatus.DRAFT,
        config=config,
    )
    db.add(row)
    _commit(db)
    return row


@router.get("/admin/config/{kind}/{key}/versions/{version_no}", response_model=VersionOut)
def get_version(
    kind: ConfigKind,
    key: str,
    version_no: int,
    _: CurrentUser = Depends(admin_only),
    db: Session = Depends(get_db),
):
    return _version(db, kind, key, version_no)


@router.put("/admin/config/{kind}/{key}/versions/{version_no}", response_model=VersionOut)
def edit_draft(
    kind: ConfigKind,
    key: str,
    version_no: int,
    body: DraftBody,
    _: CurrentUser = Depends(admin_only),
    db: Session = Depends(get_db),
):
    row = _version(db, kind, key, version_no)
    if row.status != ConfigStatus.DRAFT:
        raise HTTPException(status.HTTP_409_CONFLICT, "only a draft can be edited")
    row.config = _validated(kind, body.config)
    db.commit()
    return row


@router.post(
    "/admin/config/{kind}/{key}/versions/{version_no}/publish", response_model=VersionOut
)
def publish(
    kind: ConfigKind,
    key: str,
    version_no: int,
    _: CurrentUser = Depends(admin_only),
    db: Session = Depends(get_db),
):
    row = _version(db, kind, key, version_no)
    if row.status != ConfigStatus.DRAFT:
        raise HTTPException(status.HTTP_409_CONFLICT, "only a draft can be published")
    for old in db.scalars(
        select(m.ConfigVersion).where(
            m.ConfigVersion.kind == kind,
            m.ConfigVersion.key == key,
            m.ConfigVersion.status == ConfigStatus.PUBLISHED,
        )
    ):
        old.status = ConfigStatus.RETIRED
    row.status = ConfigStatus.PUBLISHED
    db.commit()
    return row


def latest_published(db: Session, kind: ConfigKind, key: str) -> m.ConfigVersion | None:
    return db.scalar(
        select(m.ConfigVersion)
        .where(
            m.ConfigVersion.kind == kind,
            m.ConfigVersion.key == key,
            m.ConfigVersion.status == ConfigStatus.PUBLISHED,
        )
        .order_by(m.ConfigVersion.version_no.desc())
    )


def _published(db: Session, kind: ConfigKind) -> list[m.ConfigVersion]:
    return list(
        db.scalars(
            select(m.ConfigVersion)
            .where(m.ConfigVersion.kind == kind, m.ConfigVersion.status == ConfigStatus.PUBLISHED)
            .order_by(m.ConfigVersion.key)
        )
    )


@router.get("/personas", response_model=list[PublishedItem])
def list_personas(_: CurrentUser = Depends(admin_or_trainee), db: Session = Depends(get_db)):
    return [
        PublishedItem(
            key=r.key,
            version_no=r.version_no,
            title=r.config.get("name", r.key),
            summary=r.config.get("role", ""),
        )
        for r in _published(db, ConfigKind.PERSONA)
    ]


@router.get("/scenarios", response_model=list[PublishedItem])
def list_scenarios(_: CurrentUser = Depends(admin_or_trainee), db: Session = Depends(get_db)):
    return [
        PublishedItem(
            key=r.key,
            version_no=r.version_no,
            title=r.config.get("title", r.key),
            summary=r.config.get("situation", "")[:200],
        )
        for r in _published(db, ConfigKind.SCENARIO)
    ]
