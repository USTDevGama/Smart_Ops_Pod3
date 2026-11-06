"""Upload -> real dispatch -> real Celery task -> status, with no broker.

The API's own enqueue functions and the actual `ingest_profile` / `ingest_demand` tasks run; only
the send to Redis is replaced by running the task straight away (`task.apply`), which also runs
the retries. So this checks the wiring a live worker relies on.
"""

import pytest

from app.ingest import pipeline
from app.workers import dispatch, tasks
from tests.conftest import ADMIN, ANNA
from tests.ingest_fixtures import make_docx

GOOD_DOCX = make_docx([("Experience", "Led the billing rewrite.")])
PROFILES = "/api/v1/profiles"
DEMANDS = "/api/v1/admin/demand"


@pytest.fixture
def queue(api, monkeypatch):
    """The messages sent to the queue, as (task name, id). Each task runs as soon as it is sent."""
    monkeypatch.setattr("app.ingest.router.enqueue_profile_ingest", dispatch.enqueue_profile_ingest)
    monkeypatch.setattr(
        "app.ingest.demand_router.enqueue_demand_ingest", dispatch.enqueue_demand_ingest
    )
    engine = api.factory.kw["bind"]
    monkeypatch.setattr(pipeline, "get_engine", lambda: engine)
    monkeypatch.setattr(pipeline, "get_blob_store", lambda: api.store)

    sent: list[tuple[str, str]] = []

    def run_when_sent(task):
        def delay(row_id):
            sent.append((task.name, row_id))
            task.apply(args=[row_id])

        return delay

    monkeypatch.setattr(tasks.ingest_profile, "delay", run_when_sent(tasks.ingest_profile))
    monkeypatch.setattr(tasks.ingest_demand, "delay", run_when_sent(tasks.ingest_demand))
    return sent


def upload_profile(api, data=GOOD_DOCX, name="resume.docx"):
    response = api.client.post(PROFILES, headers=ANNA, files={"file": (name, data)})
    return response, lambda: api.client.get(f"{PROFILES}/{response.json()['id']}", headers=ANNA)


def upload_demand(api, data=GOOD_DOCX, name="demand.docx"):
    response = api.client.post(DEMANDS, headers=ADMIN, files={"file": (name, data)})
    return response, lambda: api.client.get(f"{DEMANDS}/{response.json()['id']}", headers=ADMIN)


def test_a_profile_upload_is_queued_by_id_then_read_by_the_worker(api, queue):
    response, status = upload_profile(api)

    assert response.status_code == 202
    assert queue == [("ingest_profile", response.json()["id"])]  # the id only, no text
    detail = status().json()
    assert detail["status"] == "ready"
    assert "## Experience" in detail["content"]["text"]


def test_a_demand_upload_is_queued_by_id_then_read_by_the_worker(api, queue):
    response, status = upload_demand(api)

    assert response.status_code == 202
    assert queue == [("ingest_demand", response.json()["id"])]
    assert status().json()["status"] == "ready"


def test_the_same_file_again_does_not_queue_a_second_job(api, queue):
    upload_profile(api)
    again, _ = upload_profile(api)
    assert again.status_code == 200
    assert len(queue) == 1


def test_a_corrupt_file_fails_at_once_and_is_not_retried(api, queue, monkeypatch):
    calls = []
    real = pipeline.extract_markdown

    def counting(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(pipeline, "extract_markdown", counting)
    _, status = upload_profile(api, data=b"PK\x03\x04 not a docx")

    assert status().json()["status"] == "failed"
    assert status().json()["error"] == "the file could not be read"
    assert len(calls) == 1


def test_a_storage_hiccup_is_retried_and_the_row_ends_ready(api, queue, monkeypatch):
    real = pipeline.extract_markdown
    calls = []

    def flaky(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise OSError("disk hiccup")
        return real(*args, **kwargs)

    monkeypatch.setattr(pipeline, "extract_markdown", flaky)
    _, status = upload_profile(api)

    assert len(calls) == 2
    assert status().json()["status"] == "ready"


def test_a_storage_that_keeps_failing_ends_failed_after_the_retries(api, queue, monkeypatch):
    calls = []

    def always(*args, **kwargs):
        calls.append(1)
        raise OSError("disk is gone")

    monkeypatch.setattr(pipeline, "extract_markdown", always)
    _, status = upload_demand(api)

    detail = status().json()
    assert len(calls) == 1 + tasks.INGEST_RETRY["max_retries"]
    assert detail["status"] == "failed"  # never left queued or extracting
    assert detail["error"] == pipeline.GAVE_UP
