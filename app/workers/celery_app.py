from celery import Celery

from app.config import get_settings

celery_app = Celery("podc", broker=get_settings().celery_broker_url, include=["app.workers.tasks"])

celery_app.conf.update(
    task_ignore_result=True,  # results live in Postgres/blob, never in Redis
    task_acks_late=True,  # a message is only removed once the task finishes
    task_reject_on_worker_lost=True,  # a crashed worker's task is redelivered
    task_default_queue="ingest",
    task_routes={
        "ingest_proposal": {"queue": "ingest"},
        "sweep_stuck_jobs": {"queue": "ingest"},
        "run_assessment": {"queue": "assess"},
        "render_report": {"queue": "report"},
    },
)
