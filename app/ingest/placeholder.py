"""TEMPORARY stand-in for the real ingestion (Kedar's work), so chat can use a profile.

It only reads .txt files: one chunk per paragraph, and a small brief made from the first
paragraphs. The real version must keep the same outcome: `profile_segment` rows, a `Brief`
(app/schemas/profile.py) whose items cite real segment ids, and status ready or failed.
"""

from uuid import UUID

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.db import models as m
from app.db.session import get_engine
from app.schemas import Brief, BriefItem
from app.schemas.enums import FileType, ProfileStatus, SegmentKind
from app.storage import BlobStore, get_blob_store


def ingest(db: Session, profile_id: UUID, store: BlobStore) -> None:
    profile = db.get(m.Profile, profile_id)
    if profile is None or profile.status == ProfileStatus.READY:
        return  # safe to run twice
    profile.status = ProfileStatus.EXTRACTING
    db.commit()
    try:
        if profile.file_type != FileType.TXT:
            raise ValueError("the placeholder ingest only reads .txt files")
        text = store.read(profile.blob_uri).decode("utf-8")
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        if not paragraphs:
            raise ValueError("the file has no text")
        db.execute(delete(m.ProfileSegment).where(m.ProfileSegment.profile_id == profile.id))
        segments = [
            m.ProfileSegment(
                profile_id=profile.id, seq=n, page=1, kind=SegmentKind.TEXT, text=paragraph
            )
            for n, paragraph in enumerate(paragraphs, start=1)
        ]
        db.add_all(segments)
        db.flush()
        brief = Brief(
            summary=paragraphs[0][:300],
            items=[
                BriefItem(kind="claim", text=seg.text[:300], segment_ids=[seg.id])
                for seg in segments[:3]
            ],
        )
        profile.brief = brief.model_dump(mode="json")
        profile.error = None
        profile.status = ProfileStatus.READY
    except Exception as exc:
        db.rollback()
        profile = db.get(m.Profile, profile_id)
        profile.status = ProfileStatus.FAILED
        profile.error = str(exc)[:500]
    db.commit()


def ingest_in_new_session(profile_id: UUID) -> None:
    with Session(get_engine()) as db:
        ingest(db, profile_id, get_blob_store())
