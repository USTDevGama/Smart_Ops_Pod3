"""The ingest job: read a proposal's file, split it into segments, store them.

Safe to run twice. A proposal that is already `ready` is left alone, and segments are replaced
as one unit. Works on the database session it is given, so tests can use SQLite.
"""

import re
import uuid
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import Proposal, ProposalSegment
from app.ingest.chunk import SegmentDraft, to_segments
from app.ingest.extract import ExtractionError, extract_blocks
from app.ingest.storage import BlobStore
from app.schemas.enums import ProposalStatus

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
        drafts = _duplicate_drafts(session, proposal) or _read_drafts(
            proposal, store, settings, debug_dir
        )
        if not drafts:
            raise ExtractionError(NO_TEXT)
        if debug_dir is not None:
            _write_segments_dump(debug_dir, drafts)
    except ExtractionError as exc:
        _set_status(session, proposal_id, ProposalStatus.FAILED, error=str(exc))
        return
    except Exception:
        # Not the file's fault (e.g. the database is busy): hand the row back so a retry or the
        # sweeper picks it up. Nothing is left stuck in `extracting`.
        _set_status(session, proposal_id, ProposalStatus.QUEUED)
        raise

    _store_segments(session, proposal_id, drafts)
    _set_status(session, proposal_id, ProposalStatus.READY)


def _read_drafts(
    proposal: Proposal, store: BlobStore, settings: Settings, debug_dir: Path | None
) -> list[SegmentDraft]:
    path = store.path(proposal.blob_uri)
    if not path.is_file():
        raise ExtractionError(MISSING)
    blocks = extract_blocks(
        path,
        proposal.file_type,
        ocr_enabled=settings.ocr_enabled,
        ocr_lang=settings.ocr_lang,
        ocr_engine=settings.ocr_engine,
        tesseract_cmd=settings.tesseract_cmd,
        figures=settings.figures_enabled,
        figure_descriptions=settings.figure_descriptions,
        debug_dir=debug_dir,
    )
    return to_segments(blocks, settings.segment_max_chars)


def _debug_dir(settings: Settings, proposal: Proposal) -> Path | None:
    """`<debug dir>/<file name>-<id>`: the file name makes the folder recognisable."""
    if not settings.ingest_debug_dir:
        return None
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(proposal.filename).name)[:60] or "proposal"
    return Path(settings.ingest_debug_dir) / f"{name}-{str(proposal.id)[:8]}"


def _write_segments_dump(debug_dir: Path, drafts: list[SegmentDraft]) -> None:
    """A readable copy of what is about to be stored, for a developer to inspect."""
    lines = [f"{len(drafts)} segment(s)\n"]
    for draft in drafts:
        confidence = "-" if draft.ocr_confidence is None else f"{draft.ocr_confidence:.2f}"
        lines.append(
            f"=== seq={draft.seq} page={draft.page} kind={draft.kind.value} "
            f"ocr_confidence={confidence} chars={len(draft.text)}\n{draft.text}\n"
        )
    debug_dir.mkdir(parents=True, exist_ok=True)
    (debug_dir / "segments.txt").write_text("\n".join(lines), encoding="utf-8")


def _duplicate_drafts(session: Session, proposal: Proposal) -> list[SegmentDraft]:
    """Same owner, same bytes, already ingested: reuse its segments instead of parsing again."""
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
        return []
    rows = session.scalars(
        select(ProposalSegment)
        .where(ProposalSegment.proposal_id == twin.id)
        .order_by(ProposalSegment.seq)
    )
    return [
        SegmentDraft(
            seq=row.seq,
            page=row.page,
            kind=row.kind,
            text=row.text,
            ocr_confidence=row.ocr_confidence,
        )
        for row in rows
    ]


def _store_segments(session: Session, proposal_id: uuid.UUID, drafts: list[SegmentDraft]) -> None:
    session.execute(delete(ProposalSegment).where(ProposalSegment.proposal_id == proposal_id))
    session.add_all(
        ProposalSegment(
            proposal_id=proposal_id,
            seq=draft.seq,
            page=draft.page,
            kind=draft.kind,
            text=draft.text,
            ocr_confidence=draft.ocr_confidence,
        )
        for draft in drafts
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
