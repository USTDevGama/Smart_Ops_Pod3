"""TEMPORARY stand-in for the real ingestion (Kedar's work), so chat can use a proposal.

It only reads .txt files: one chunk per paragraph, and a small brief made from the first
paragraphs. The real version must keep the same outcome: `proposal_segment` rows, a `Brief`
(app/schemas/proposal.py) whose items cite real segment ids, and status ready or failed.
"""

from uuid import UUID

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.db import models as m
from app.db.session import get_engine
from app.schemas import Brief, BriefItem
from app.schemas.enums import FileType, ProposalStatus, SegmentKind
from app.storage import BlobStore, get_blob_store


def ingest(db: Session, proposal_id: UUID, store: BlobStore) -> None:
    proposal = db.get(m.Proposal, proposal_id)
    if proposal is None or proposal.status == ProposalStatus.READY:
        return  # safe to run twice
    proposal.status = ProposalStatus.EXTRACTING
    db.commit()
    try:
        if proposal.file_type != FileType.TXT:
            raise ValueError("the placeholder ingest only reads .txt files")
        text = store.read(proposal.blob_uri).decode("utf-8")
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        if not paragraphs:
            raise ValueError("the file has no text")
        db.execute(delete(m.ProposalSegment).where(m.ProposalSegment.proposal_id == proposal.id))
        segments = [
            m.ProposalSegment(
                proposal_id=proposal.id, seq=n, page=1, kind=SegmentKind.TEXT, text=paragraph
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
        proposal.brief = brief.model_dump(mode="json")
        proposal.error = None
        proposal.status = ProposalStatus.READY
    except Exception as exc:
        db.rollback()
        proposal = db.get(m.Proposal, proposal_id)
        proposal.status = ProposalStatus.FAILED
        proposal.error = str(exc)[:500]
    db.commit()


def ingest_in_new_session(proposal_id: UUID) -> None:
    with Session(get_engine()) as db:
        ingest(db, proposal_id, get_blob_store())
