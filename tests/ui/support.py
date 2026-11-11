"""Shared helpers for the UI tests: the morning set-up of the story, played through the client."""

import json

from app.ingest import pipeline
from app.schemas import Evaluation, TurnOutput
from ui.client import PodCClient
from ui.persona_form import default_persona, default_scenarios_json


def output(quality=0.3, level=2, reply="Be specific."):
    return TurnOutput(
        evaluation=Evaluation(
            answer_quality=quality, checklist_met=[], quote="x", proposed_level=level
        ),
        reply=reply,
    )


class ScriptedEngine:
    """Hands out prepared replies; raises an exception when told to."""

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = 0

    def opening(self, ctx):
        return output(reply="When were you going to tell me?")

    def respond(self, ctx, answer):
        self.calls += 1
        item = self.outputs.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def clients(api, http=None):
    http = http or api.client
    return (
        PodCClient(user="admin1", role="admin", http=http),
        PodCClient(user="anna", role="trainee", http=http),
    )


def stage(api, persona: dict | None = None, http=None):
    """The admin sets the stage, then Anna uploads her resume. Returns (admin, anna, profile_id)."""
    admin, anna = clients(api, http)
    admin.create_persona("verma-strict", persona or default_persona())
    admin.publish_persona("verma-strict", 1)
    admin.import_scenarios(json.loads(default_scenarios_json()))

    admin.upload_demand("demand.txt", b"Billing modernisation. The invoicing release is due soon.")
    with api.factory() as db:
        pipeline.ingest_demand(db, api.queued_demand[-1], api.store)

    resume = anna.upload_profile("resume.txt", b"Backend engineer. Led a billing rewrite.")
    with api.factory() as db:
        pipeline.ingest_profile(db, api.queued[-1], api.store)
    return admin, anna, resume.row["id"]


REPORT_FILES = {
    "pdf": ("report.pdf", b"%PDF-1.4 a made-up report"),
    "html": ("report.html", b"<html>made-up report</html>"),
    "md": ("report.md", b"# Report\n\nOverall score: 47.5"),
}


def write_report(api, session_id: str) -> None:
    """Put the three report files where the post-session job would have put them."""
    for filename, data in REPORT_FILES.values():
        api.store.save(data, name=f"reports/{session_id}/{filename}")
