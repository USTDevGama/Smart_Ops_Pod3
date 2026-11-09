import importlib

import pytest

import app.workers.tasks  # noqa: F401  (registers the tasks; Celery loads them lazily)
from app.workers.celery_app import celery_app


@pytest.mark.parametrize(
    "package", ["app.ingest", "app.agent", "app.scoring", "app.reports", "app.workers", "app.api"]
)
def test_each_owner_package_imports(package):
    importlib.import_module(package)


def test_worker_defaults_are_safe():
    conf = celery_app.conf
    assert conf.task_ignore_result is True
    assert conf.task_acks_late is True
    assert conf.task_reject_on_worker_lost is True


def test_jobs_are_routed_to_their_queues():
    routes = celery_app.conf.task_routes
    assert routes["ingest_profile"]["queue"] == "ingest"
    assert routes["ingest_demand"]["queue"] == "ingest"
    assert routes["run_assessment"]["queue"] == "assess"
    assert "render_report" not in routes  # scoring and the report are one job
    for name in routes:
        assert name in celery_app.tasks
