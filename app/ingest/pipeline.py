"""The ingest job: read a proposal's file as markdown and store it as one row.

Safe to run twice. A proposal that is already `ready` is left alone, and the stored row is
replaced as one unit. Works on the database session it is given, so tests can use SQLite.
"""

import re
import uuid
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import Proposal, ProposalSegment
from app.ingest.errors import ExtractionError
from app.ingest.extract import extract_markdown
from app.ingest.storage import BlobStore
from app.schemas.enums import ProposalStatus, SegmentKind

NO_TEXT = "no readable text was found in the file"
MISSING = "the uploaded file could not be found"


def run_ingest(
    session: Session, proposal_id: uuid.UUID, store: BlobStore, settings: Settings
) -> None:
    proposal = session.get(Proposal, proposal_id)
    if proposal is None or proposal.status is ProposalStatus.READY:
        return
    proposal.status = ProposalStatus.EXTRACTING
    session.commit()

    debug_dir = _debug_dir(settings, proposal)
    try:
        text = _duplicate_text(session, proposal) or _read_text(proposal, store)
        if not text:
            raise ExtractionError(NO_TEXT)
        if debug_dir is not None:
            _write_dump(debug_dir, text)
    except ExtractionError as exc:
        _set_status(session, proposal_id, ProposalStatus.FAILED, error=str(exc))
        return
    except Exception:
        # Not the file's fault (e.g. the database is busy): hand the row back so a retry or the
        # sweeper picks it up. Nothing is left stuck in `extracting`.
        _set_status(session, proposal_id, ProposalStatus.QUEUED)
        raise

    _store_text(session, proposal_id, text)
    _set_status(session, proposal_id, ProposalStatus.READY)


def _read_text(proposal: Proposal, store: BlobStore) -> str:
    path = store.path(proposal.blob_uri)
    if not path.is_file():
        raise ExtractionError(MISSING)
    return extract_markdown(path, proposal.file_type)


def _debug_dir(settings: Settings, proposal: Proposal) -> Path | None:
    """`<debug dir>/<file name>-<id>`: the file name makes the folder recognisable."""
    if not settings.ingest_debug_dir:
        return None
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(proposal.filename).name)[:60] or "proposal"
    return Path(settings.ingest_debug_dir) / f"{name}-{str(proposal.id)[:8]}"


def _write_dump(debug_dir: Path, text: str) -> None:
    """A readable copy of what is about to be stored, for a developer to inspect."""
    debug_dir.mkdir(parents=True, exist_ok=True)
    (debug_dir / "document.md").write_text(text, encoding="utf-8")


def _duplicate_text(session: Session, proposal: Proposal) -> str:
    """Same owner, same bytes, already ingested: reuse its text instead of parsing again."""
    twin = session.scalar(
        select(Proposal)
        .where(
            Proposal.owner_id == proposal.owner_id,
            Proposal.sha256 == proposal.sha256,
            Proposal.status == ProposalStatus.READY,
            Proposal.id != proposal.id,
        )
        .limit(1)
    )
    if twin is None:
        return ""
    texts = session.scalars(
        select(ProposalSegment.text)
        .where(ProposalSegment.proposal_id == twin.id)
        .order_by(ProposalSegment.seq)
    )
    return "\n\n".join(texts)


def _store_text(session: Session, proposal_id: uuid.UUID, text: str) -> None:
    session.execute(delete(ProposalSegment).where(ProposalSegment.proposal_id == proposal_id))
    session.add(
        ProposalSegment(
            proposal_id=proposal_id,
            seq=0,
            page=1,
            kind=SegmentKind.TEXT,
            text=text,
        )
    )
    session.commit()


def _set_status(
    session: Session, proposal_id: uuid.UUID, status: ProposalStatus, error: str | None = None
) -> None:
    # Rollback first: a failed flush leaves the session unusable until it is reset.
    session.rollback()
    proposal = session.get(Proposal, proposal_id)
    proposal.status = status
    proposal.error = error
    session.commit()
