import hashlib
import uuid

import pytest
from sqlalchemy import select

from app.config import Settings
from app.db.models import AppUser, Proposal, ProposalSegment
from app.ingest import pipeline
from app.ingest.pdf_text import NO_TEXT_LAYER
from app.ingest.pipeline import MISSING, NO_TEXT, run_ingest
from app.ingest.storage import BlobStore
from app.schemas.enums import FileType, ProposalStatus, SegmentKind
from tests.ingest_fixtures import make_docx, make_pdf, make_scanned_pdf, make_text_pdf

SETTINGS = Settings()


@pytest.fixture
def store(tmp_path):
    return BlobStore(tmp_path)


@pytest.fixture
def owner(db):
    user = AppUser(idp_sub="trainee-a")
    db.add(user)
    db.commit()
    return user


def queue_proposal(db, store, owner, data: bytes, file_type: FileType) -> Proposal:
    """Store the bytes and insert a queued row, as the upload endpoint does."""
    proposal_id = uuid.uuid4()
    key = f"proposals/{proposal_id}/original.{file_type.value}"
    store.save(key, data)

    proposal = Proposal(
        id=proposal_id,
        owner_id=owner.id,
        filename=f"plan.{file_type.value}",
        file_type=file_type,
        sha256=hashlib.sha256(data).hexdigest(),
        blob_uri=key,
        status=ProposalStatus.QUEUED,
    )
    db.add(proposal)
    db.commit()
    return proposal


def stored_rows(db, proposal_id):
    return db.scalars(
        select(ProposalSegment)
        .where(ProposalSegment.proposal_id == proposal_id)
        .order_by(ProposalSegment.seq)
    ).all()


def stored_text(db, proposal_id) -> str:
    """The one row that holds the whole document."""
    (row,) = stored_rows(db, proposal_id)
    return row.text


def test_txt_becomes_ready_with_one_markdown_row(db, store, owner):
    body = b"Budget is 400000.\n\nTimeline is six months.\n\nVendor is CloudPay."
    proposal = queue_proposal(db, store, owner, body, FileType.TXT)

    run_ingest(db, proposal.id, store, SETTINGS)

    db.refresh(proposal)
    assert proposal.status is ProposalStatus.READY
    assert proposal.error is None
    (row,) = stored_rows(db, proposal.id)
    assert row.text == "Budget is 400000.\n\nTimeline is six months.\n\nVendor is CloudPay."
    assert (row.seq, row.page, row.kind) == (0, 1, SegmentKind.TEXT)


def test_a_long_document_is_stored_whole_in_one_row(db, store, owner):
    body = "\n\n".join(f"Paragraph {n} says the budget is {n} thousand." for n in range(400))
    proposal = queue_proposal(db, store, owner, body.encode(), FileType.TXT)

    run_ingest(db, proposal.id, store, SETTINGS)

    assert stored_text(db, proposal.id) == body


def test_running_twice_gives_the_same_text(db, store, owner):
    proposal = queue_proposal(db, store, owner, b"One.\n\nTwo.", FileType.TXT)
    run_ingest(db, proposal.id, store, SETTINGS)
    first = stored_text(db, proposal.id)

    run_ingest(db, proposal.id, store, SETTINGS)  # a retry: the row is already ready

    assert stored_text(db, proposal.id) == first


def test_native_pdf_is_ingested(db, store, owner):
    proposal = queue_proposal(
        db, store, owner, make_pdf(["Budget is 400000 dollars."]), FileType.PDF
    )
    run_ingest(db, proposal.id, store, SETTINGS)
    db.refresh(proposal)
    assert proposal.status is ProposalStatus.READY
    assert "400000" in stored_text(db, proposal.id)


def test_corrupt_file_fails_with_a_safe_message(db, store, owner):
    proposal = queue_proposal(db, store, owner, b"%PDF-1.4 SECRET not a pdf", FileType.PDF)

    run_ingest(db, proposal.id, store, SETTINGS)

    db.refresh(proposal)
    assert proposal.status is ProposalStatus.FAILED
    assert proposal.error == "the file could not be read"
    assert "SECRET" not in proposal.error
    assert stored_rows(db, proposal.id) == []


def test_blank_file_fails_with_no_text(db, store, owner):
    proposal = queue_proposal(db, store, owner, b"   \n\n  ", FileType.TXT)
    run_ingest(db, proposal.id, store, SETTINGS)
    db.refresh(proposal)
    assert proposal.status is ProposalStatus.FAILED
    assert proposal.error == NO_TEXT


def test_missing_blob_fails_cleanly(db, store, owner):
    proposal = queue_proposal(db, store, owner, b"text", FileType.TXT)
    store.delete(proposal.blob_uri)

    run_ingest(db, proposal.id, store, SETTINGS)

    db.refresh(proposal)
    assert proposal.status is ProposalStatus.FAILED
    assert proposal.error == MISSING


def test_same_file_from_same_owner_reuses_the_text(db, store, owner, monkeypatch):
    data = b"Budget is 400000.\n\nNo risks listed."
    first = queue_proposal(db, store, owner, data, FileType.TXT)
    run_ingest(db, first.id, store, SETTINGS)

    def no_parsing(*args, **kwargs):
        raise AssertionError("a duplicate must not be parsed again")

    monkeypatch.setattr(pipeline, "extract_markdown", no_parsing)
    second = queue_proposal(db, store, owner, data, FileType.TXT)
    run_ingest(db, second.id, store, SETTINGS)

    db.refresh(second)
    assert second.status is ProposalStatus.READY
    assert stored_text(db, second.id) == stored_text(db, first.id)


def test_other_owners_copy_is_not_reused(db, store, owner, monkeypatch):
    data = b"Shared text."
    run_ingest(db, queue_proposal(db, store, owner, data, FileType.TXT).id, store, SETTINGS)
    other = AppUser(idp_sub="trainee-b")
    db.add(other)
    db.commit()

    parsed = []
    real = pipeline.extract_markdown

    def spy(*args, **kwargs):
        parsed.append(True)
        return real(*args, **kwargs)

    monkeypatch.setattr(pipeline, "extract_markdown", spy)
    proposal = queue_proposal(db, store, other, data, FileType.TXT)
    run_ingest(db, proposal.id, store, SETTINGS)

    assert parsed == [True]


def test_transient_error_puts_the_row_back_in_queued_and_raises(db, store, owner, monkeypatch):
    proposal = queue_proposal(db, store, owner, b"text", FileType.TXT)

    def flaky(*args, **kwargs):
        raise OSError("disk hiccup")

    monkeypatch.setattr(pipeline, "extract_markdown", flaky)
    with pytest.raises(OSError):
        run_ingest(db, proposal.id, store, SETTINGS)

    db.refresh(proposal)
    assert proposal.status is ProposalStatus.QUEUED  # not stuck in "extracting"
    assert proposal.error is None


def test_debug_dump_is_written_only_when_asked(db, store, owner, tmp_path):
    proposal = queue_proposal(db, store, owner, b"Budget is 400000.", FileType.TXT)
    run_ingest(db, proposal.id, store, Settings())  # no debug dir set
    assert not (tmp_path / "debug").exists()

    other = queue_proposal(db, store, owner, b"Timeline is six months.", FileType.TXT)
    debug = tmp_path / "debug"
    run_ingest(db, other.id, store, Settings(ingest_debug_dir=str(debug)))

    (folder,) = debug.iterdir()
    assert folder.name.startswith("plan.txt-")  # recognisable by file name
    assert (folder / "document.md").read_text(encoding="utf-8") == "Timeline is six months."


def test_scanned_pdf_fails_with_the_clear_message(db, store, owner):
    proposal = queue_proposal(db, store, owner, make_scanned_pdf("Budget 400000"), FileType.PDF)

    run_ingest(db, proposal.id, store, SETTINGS)

    db.refresh(proposal)
    assert proposal.status is ProposalStatus.FAILED
    assert proposal.error == NO_TEXT_LAYER
    assert stored_rows(db, proposal.id) == []


def test_docx_with_a_table_is_ingested(db, store, owner):
    data = make_docx(
        [("Budget", "The total budget is 400000.")], table=[["Item", "Cost"], ["A", "1"]]
    )
    proposal = queue_proposal(db, store, owner, data, FileType.DOCX)

    run_ingest(db, proposal.id, store, Settings())

    db.refresh(proposal)
    assert proposal.status is ProposalStatus.READY
    text = stored_text(db, proposal.id)
    assert "## Budget" in text and "400000" in text and "| Item | Cost |" in text


def test_text_pdf_with_a_table_is_ingested(db, store, owner):
    data = make_text_pdf([["Options compared"]], table=[["Option", "Cost"], ["A", "100"]])
    proposal = queue_proposal(db, store, owner, data, FileType.PDF)

    run_ingest(db, proposal.id, store, Settings())

    db.refresh(proposal)
    assert proposal.status is ProposalStatus.READY
    assert "| Option | Cost |" in stored_text(db, proposal.id)


def test_unknown_proposal_is_a_no_op(db, store):
    run_ingest(db, uuid.uuid4(), store, SETTINGS)  # must not raise
