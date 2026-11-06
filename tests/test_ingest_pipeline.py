import uuid

import pytest

from app.db import models as m
from app.ingest import pipeline
from app.ingest.errors import TransientIngestError
from app.ingest.pipeline import FAILED, GAVE_UP, MISSING, NO_TEXT
from app.schemas.enums import FileType, IngestStatus
from app.storage import LocalBlobStore

KINDS = [
    pytest.param(m.Profile, pipeline.ingest_profile, id="profile"),
    pytest.param(m.DemandDocument, pipeline.ingest_demand, id="demand"),
]


@pytest.fixture
def store(tmp_path):
    return LocalBlobStore(tmp_path / "blobs")


def queued_row(db, store, model, data: bytes, file_type: FileType = FileType.TXT):
    """Store the bytes and insert a queued row, as the upload endpoints do."""
    fields = {
        "filename": f"file.{file_type.value}",
        "file_type": file_type,
        "sha256": uuid.uuid4().hex * 2,
        "blob_uri": store.save(data, f".{file_type.value}"),
        "status": IngestStatus.QUEUED,
    }
    owner = {"owner_ref": "anna"} if model is m.Profile else {"uploaded_by": "admin1"}
    row = model(**owner, **fields)
    db.add(row)
    db.commit()
    return row


@pytest.mark.parametrize(("model", "ingest"), KINDS)
def test_txt_becomes_ready_and_the_whole_text_is_kept(db, store, model, ingest):
    row = queued_row(db, store, model, b"Budget is 400000.\n\nTimeline is six months.")

    ingest(db, row.id, store)

    db.refresh(row)
    assert row.status is IngestStatus.READY
    assert row.error is None
    assert row.content == {"text": "Budget is 400000.\n\nTimeline is six months."}


@pytest.mark.parametrize(("model", "ingest"), KINDS)
def test_a_long_document_is_kept_whole(db, store, model, ingest):
    body = "\n\n".join(f"Paragraph {n} says the budget is {n} thousand." for n in range(400))
    row = queued_row(db, store, model, body.encode())

    ingest(db, row.id, store)

    db.refresh(row)
    assert row.content == {"text": body}


@pytest.mark.parametrize(("model", "ingest"), KINDS)
def test_running_twice_leaves_a_ready_row_alone(db, store, model, ingest, monkeypatch):
    row = queued_row(db, store, model, b"One.\n\nTwo.")
    ingest(db, row.id, store)

    def no_reading(*args, **kwargs):
        raise AssertionError("a ready row must not be read again")

    monkeypatch.setattr(pipeline, "extract_markdown", no_reading)
    ingest(db, row.id, store)  # a retry

    db.refresh(row)
    assert row.status is IngestStatus.READY
    assert row.content == {"text": "One.\n\nTwo."}


@pytest.mark.parametrize(("model", "ingest"), KINDS)
def test_a_blank_file_fails_with_no_text(db, store, model, ingest):
    row = queued_row(db, store, model, b"   \n\n  ")

    ingest(db, row.id, store)

    db.refresh(row)
    assert row.status is IngestStatus.FAILED
    assert row.error == NO_TEXT
    assert row.content is None


@pytest.mark.parametrize(("model", "ingest"), KINDS)
def test_a_missing_file_fails_cleanly(db, store, model, ingest):
    row = queued_row(db, store, model, b"text")
    store.delete(row.blob_uri)

    ingest(db, row.id, store)

    db.refresh(row)
    assert row.status is IngestStatus.FAILED
    assert row.error == MISSING


@pytest.mark.parametrize(("model", "ingest"), KINDS)
def test_an_unexpected_error_gives_a_fixed_message_and_leaks_nothing(
    db, store, model, ingest, monkeypatch
):
    row = queued_row(db, store, model, b"text")

    def broken(*args, **kwargs):
        raise RuntimeError("SECRET resume text")

    monkeypatch.setattr(pipeline, "extract_markdown", broken)
    ingest(db, row.id, store)

    db.refresh(row)
    assert row.status is IngestStatus.FAILED
    assert row.error == FAILED
    assert "SECRET" not in row.error


@pytest.mark.parametrize(("model", "ingest"), KINDS)
def test_a_corrupt_docx_fails_with_the_fixed_message(db, store, model, ingest):
    row = queued_row(db, store, model, b"PK\x03\x04 SECRET not a docx", FileType.DOCX)

    ingest(db, row.id, store)

    db.refresh(row)
    assert row.status is IngestStatus.FAILED
    assert row.error == "the file could not be read"


@pytest.mark.parametrize(("model", "ingest"), KINDS)
def test_a_storage_hiccup_puts_the_row_back_to_queued_and_asks_for_a_retry(
    db, store, model, ingest, monkeypatch
):
    row = queued_row(db, store, model, b"text")

    def hiccup(*args, **kwargs):
        raise OSError("SECRET disk hiccup")

    monkeypatch.setattr(pipeline, "extract_markdown", hiccup)
    with pytest.raises(TransientIngestError):
        ingest(db, row.id, store)

    db.refresh(row)
    assert row.status is IngestStatus.QUEUED  # not stuck in "extracting"
    assert row.error is None


@pytest.mark.parametrize(("model", "ingest"), KINDS)
def test_on_the_last_attempt_a_storage_hiccup_fails_the_row(db, store, model, ingest, monkeypatch):
    row = queued_row(db, store, model, b"text")

    def hiccup(*args, **kwargs):
        raise OSError("SECRET disk hiccup")

    monkeypatch.setattr(pipeline, "extract_markdown", hiccup)
    ingest(db, row.id, store, last_attempt=True)  # does not raise: nothing is left waiting

    db.refresh(row)
    assert row.status is IngestStatus.FAILED
    assert row.error == GAVE_UP
    assert "SECRET" not in row.error


def test_an_unknown_id_is_a_no_op(db, store):
    pipeline.ingest_profile(db, uuid.uuid4(), store)  # must not raise
    pipeline.ingest_demand(db, uuid.uuid4(), store)
