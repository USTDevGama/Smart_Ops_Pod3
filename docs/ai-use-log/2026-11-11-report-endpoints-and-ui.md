# 2026-11-11 - report endpoints and the report panel in the Streamlit UI

- **Tool:** Claude Code (running inside VS Code).
- **Account:** TODO - the committer fills in the work account used.
- **What was shared:** this repository's own code and docs (the scoring pipeline, report generator, blob store and chat service). No seed-pack content, no secrets, no keys, no real trainee data. All test data is made-up.
- **What came back:** `app/api/reports.py` (report status, make-sure-it-is-generated, admin download), a temp-folder fallback in `app/storage.py`, a raising variant of the job sender in `app/workers/dispatch.py`, a report panel in the UI (`ui/widgets.py` and the chat and review pages), tests, a regenerated `docs/openapi.yaml` and doc updates.
- **Review:** TODO - the committer and a teammate confirm they have read and can explain every file before relying on it.
- **Known gaps to check by a person:**
  - Only admins can download the report (it carries the suggested mark). Whether trainees may see their own report is a product decision for the scoring owner.
  - With the fake model provider no report can be produced; the UI says so. A real model has to be configured to see one end to end.
  - The 5-minute wait before a lost job is sent again is a guess, not a measured retry window.
  - The pages were exercised headlessly and through the real API, not yet in a browser.
