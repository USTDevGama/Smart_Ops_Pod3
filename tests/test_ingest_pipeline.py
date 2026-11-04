import uuid

import pytest
from sqlalchemy import select

from app.config import Settings
from app.db.models import AppUser, Proposal, ProposalSegment
from app.ingest import pipeline
from app.ingest.extract import OcrUnavailable
from app.ingest.pipeline import MISSING, NO_TEXT, run_ingest
from app.ingest.storage import BlobStore
from app.schemas.enums import FileType, ProposalStatus, SegmentKind
from tests.ingest_fixtures import make_chart_png, make_pdf, make_scanned_pdf

SETTINGS = Settings(ocr_enabled=False, segment_max_chars=200)


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
    import hashlib

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


def segments_of(db, proposal_id):
    return db.scalars(
        select(ProposalSegment)
        .where(ProposalSegment.proposal_id == proposal_id)
        .order_by(ProposalSegment.seq)
    ).all()


def test_txt_becomes_ready_with_ordered_segments(db, store, owner):
    body = b"Budget is 400000.\n\nTimeline is six months.\n\nVendor is CloudPay."
    proposal = queue_proposal(db, store, owner, body, FileType.TXT)

    run_ingest(db, proposal.id, store, SETTINGS)

    db.refresh(proposal)
    assert proposal.status is ProposalStatus.READY
    assert proposal.error is None
    rows = segments_of(db, proposal.id)
    assert [r.seq for r in rows] == list(range(len(rows)))
    assert "CloudPay" in " ".join(r.text for r in rows)
    assert {r.page for r in rows} == {1}


def test_running_twice_gives_the_same_segments(db, store, owner):
    proposal = queue_proposal(db, store, owner, b"One.\n\nTwo.", FileType.TXT)
    run_ingest(db, proposal.id, store, SETTINGS)
    first = [(r.seq, r.text) for r in segments_of(db, proposal.id)]

    run_ingest(db, proposal.id, store, SETTINGS)  # a retry: the row is already ready

    assert [(r.seq, r.text) for r in segments_of(db, proposal.id)] == first


def test_native_pdf_is_ingested(db, store, owner):
    proposal = queue_proposal(
        db, store, owner, make_pdf(["Budget is 400000 dollars."]), FileType.PDF
    )
    run_ingest(db, proposal.id, store, SETTINGS)
    db.refresh(proposal)
    assert proposal.status is ProposalStatus.READY
    assert "400000" in " ".join(r.text for r in segments_of(db, proposal.id))


def test_corrupt_file_fails_with_a_safe_message(db, store, owner):
    proposal = queue_proposal(db, store, owner, b"%PDF-1.4 SECRET not a pdf", FileType.PDF)

    run_ingest(db, proposal.id, store, SETTINGS)

    db.refresh(proposal)
    assert proposal.status is ProposalStatus.FAILED
    assert proposal.error == "the file could not be read"
    assert "SECRET" not in proposal.error
    assert segments_of(db, proposal.id) == []


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


def test_same_file_from_same_owner_reuses_segments(db, store, owner, monkeypatch):
    data = b"Budget is 400000.\n\nNo risks listed."
    first = queue_proposal(db, store, owner, data, FileType.TXT)
    run_ingest(db, first.id, store, SETTINGS)

    def no_parsing(*args, **kwargs):
        raise AssertionError("a duplicate must not be parsed again")

    monkeypatch.setattr(pipeline, "extract_blocks", no_parsing)
    second = queue_proposal(db, store, owner, data, FileType.TXT)
    run_ingest(db, second.id, store, SETTINGS)

    db.refresh(second)
    assert second.status is ProposalStatus.READY
    assert [(r.seq, r.text) for r in segments_of(db, second.id)] == [
        (r.seq, r.text) for r in segments_of(db, first.id)
    ]


def test_other_owners_copy_is_not_reused(db, store, owner, monkeypatch):
    data = b"Shared text."
    run_ingest(db, queue_proposal(db, store, owner, data, FileType.TXT).id, store, SETTINGS)
    other = AppUser(idp_sub="trainee-b")
    db.add(other)
    db.commit()

    parsed = []
    real = pipeline.extract_blocks

    def spy(*args, **kwargs):
        parsed.append(True)
        return real(*args, **kwargs)

    monkeypatch.setattr(pipeline, "extract_blocks", spy)
    proposal = queue_proposal(db, store, other, data, FileType.TXT)
    run_ingest(db, proposal.id, store, SETTINGS)

    assert parsed == [True]


def test_transient_error_puts_the_row_back_in_queued_and_raises(db, store, owner, monkeypatch):
    proposal = queue_proposal(db, store, owner, b"text", FileType.TXT)

    def flaky(*args, **kwargs):
        raise OSError("disk hiccup")

    monkeypatch.setattr(pipeline, "extract_blocks", flaky)
    with pytest.raises(OSError):
        run_ingest(db, proposal.id, store, SETTINGS)

    db.refresh(proposal)
    assert proposal.status is ProposalStatus.QUEUED  # not stuck in "extracting"
    assert proposal.error is None


NO_OCR_BINARY = Settings(
    ocr_enabled=True, ocr_engine="tesseract", tesseract_cmd="no-such-tesseract-binary"
)


def test_scanned_pdf_without_tesseract_is_requeued_not_failed(db, store, owner):
    proposal = queue_proposal(db, store, owner, make_scanned_pdf("Budget 400000"), FileType.PDF)

    with pytest.raises(OcrUnavailable):
        run_ingest(db, proposal.id, store, NO_OCR_BINARY)

    db.refresh(proposal)
    assert proposal.status is ProposalStatus.QUEUED  # a retry can succeed once OCR is installed
    assert proposal.error is None


def test_native_pdf_and_txt_ingest_even_when_tesseract_is_missing(db, store, owner):
    pdf = queue_proposal(db, store, owner, make_pdf(["Budget is 400000."]), FileType.PDF)
    txt = queue_proposal(db, store, owner, b"Timeline is six months.", FileType.TXT)

    run_ingest(db, pdf.id, store, NO_OCR_BINARY)
    run_ingest(db, txt.id, store, NO_OCR_BINARY)

    db.refresh(pdf)
    db.refresh(txt)
    assert pdf.status is ProposalStatus.READY
    assert txt.status is ProposalStatus.READY


def test_scanned_pdf_is_ingested_with_rapidocr_segments(db, store, owner):
    proposal = queue_proposal(
        db, store, owner, make_scanned_pdf("Budget is 400000 dollars"), FileType.PDF
    )

    run_ingest(db, proposal.id, store, Settings(ocr_enabled=True, ocr_engine="rapidocr"))

    db.refresh(proposal)
    assert proposal.status is ProposalStatus.READY
    rows = segments_of(db, proposal.id)
    assert rows and {r.kind for r in rows} == {SegmentKind.OCR}
    assert all(r.ocr_confidence is not None for r in rows)
    assert "400000" in " ".join(r.text for r in rows)


def test_debug_dump_is_written_only_when_asked(db, store, owner, tmp_path):
    proposal = queue_proposal(db, store, owner, b"Budget is 400000.", FileType.TXT)
    run_ingest(db, proposal.id, store, Settings(ocr_enabled=False))  # no debug dir set
    assert not (tmp_path / "debug").exists()

    other = queue_proposal(db, store, owner, b"Timeline is six months.", FileType.TXT)
    debug = tmp_path / "debug"
    run_ingest(db, other.id, store, Settings(ocr_enabled=False, ingest_debug_dir=str(debug)))

    (folder,) = debug.iterdir()
    assert folder.name.startswith("plan.txt-")  # recognisable by file name
    dump = (folder / "segments.txt").read_text(encoding="utf-8")
    assert "1 segment(s)" in dump and "Timeline is six months." in dump
    assert "kind=text" in dump


def test_pdf_debug_dump_has_docling_output_and_figure_crops(db, store, owner, tmp_path):
    data = make_pdf(["Budget below."], make_chart_png(), "Figure 1: Budget by quarter")
    proposal = queue_proposal(db, store, owner, data, FileType.PDF)
    debug = tmp_path / "debug"

    run_ingest(db, proposal.id, store, Settings(ocr_enabled=False, ingest_debug_dir=str(debug)))

    (folder,) = debug.iterdir()
    assert {p.name for p in folder.iterdir()} == {
        "docling.md",
        "segments.txt",
        "figure-1-page1.png",
    }
    assert "kind=figure" in (folder / "segments.txt").read_text(encoding="utf-8")
    assert {r.kind for r in segments_of(db, proposal.id)} == {SegmentKind.TEXT, SegmentKind.FIGURE}


def test_unknown_proposal_is_a_no_op(db, store):
    run_ingest(db, uuid.uuid4(), store, SETTINGS)  # must not raise


def test_segment_kind_defaults_to_text_for_plain_files(db, store, owner):
    proposal = queue_proposal(db, store, owner, b"plain", FileType.TXT)
    run_ingest(db, proposal.id, store, SETTINGS)
    assert {r.kind for r in segments_of(db, proposal.id)} == {SegmentKind.TEXT}
