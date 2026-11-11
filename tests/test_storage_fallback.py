"""The blob folder: used when it works, a temp folder when it does not."""

from types import SimpleNamespace

import pytest

from app import storage
from app.storage import FALLBACK_DIR_NAME, get_blob_store


@pytest.fixture(autouse=True)
def fresh_check():
    """The folder check is remembered per folder: forget it around every test."""
    storage._usable_root.cache_clear()
    yield
    storage._usable_root.cache_clear()


def configure(monkeypatch, tmp_path, blob_dir):
    monkeypatch.setattr(storage, "get_settings", lambda: SimpleNamespace(blob_dir=str(blob_dir)))
    monkeypatch.setattr(storage.tempfile, "gettempdir", lambda: str(tmp_path / "system-temp"))


def test_a_working_folder_is_used_and_created(monkeypatch, tmp_path):
    folder = tmp_path / "blobs" / "nested"
    configure(monkeypatch, tmp_path, folder)

    store = get_blob_store()
    uri = store.save(b"data", name="reports/x/report.pdf")

    assert store.root == folder
    assert (folder / "reports" / "x" / "report.pdf").read_bytes() == b"data"
    assert store.read(uri) == b"data"
    assert not any(p.name.startswith(".write-test") for p in folder.iterdir())  # probe cleaned up


def test_a_folder_that_cannot_be_written_falls_back_to_a_temp_folder(monkeypatch, tmp_path, caplog):
    blocked = tmp_path / "not-a-folder"
    blocked.write_text("a file is in the way")  # a folder can never be created here
    configure(monkeypatch, tmp_path, blocked)

    store = get_blob_store()
    store.save(b"report", name="reports/x/report.pdf")

    assert store.root == tmp_path / "system-temp" / FALLBACK_DIR_NAME
    assert store.read("reports/x/report.pdf") == b"report"
    assert "cannot be written" in caplog.text


def test_the_fallback_is_the_same_place_every_time(monkeypatch, tmp_path):
    """The API and the worker are separate processes: both must find the same folder."""
    blocked = tmp_path / "not-a-folder"
    blocked.write_text("in the way")
    configure(monkeypatch, tmp_path, blocked)

    get_blob_store().save(b"from the worker", name="reports/x/report.md")

    assert get_blob_store().read("reports/x/report.md") == b"from the worker"


def test_the_fallback_is_logged_once_not_on_every_request(monkeypatch, tmp_path, caplog):
    blocked = tmp_path / "not-a-folder"
    blocked.write_text("in the way")
    configure(monkeypatch, tmp_path, blocked)

    for _ in range(5):
        get_blob_store()

    assert caplog.text.count("cannot be written") == 1
