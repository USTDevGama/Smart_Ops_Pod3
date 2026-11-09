# 2026-11-09 - post-session scoring pipeline and report wiring (Disha)

- **Tool:** GitHub Copilot (agent mode in VS Code).
- **Account:** TODO - fill in the work account used.
- **What was shared:** this repo's code and its branches, read from a local checkout (including the teammates' `feature/podc-scoring-llm-call` branch, merged into `d/end-to-end`). No real trainee data, no seed pack, no credentials. The tests use made-up chats, resumes and demand text.
- **What came back and where it went:**
  - the fixed four-criterion rubric (`app/scoring/rubric.py`, `samples/scoring/default.json`), a `description` field on `CriterionConfig`, `handled_cutoffs`, and new confidence weights;
  - code markers per trainee answer (`app/scoring/signals.py`), rule-based client-message validity (`app/scoring/validity.py`) and small text helpers (`app/scoring/text.py`);
  - `derive_handled` in `app/scoring/processor.py`;
  - the pipeline (`app/scoring/pipeline.py`), the single Celery task `run_assessment` (score, then report), `enqueue_assessment` in `app/workers/dispatch.py` and the session-end hook;
  - the report no longer needs a scenario; named blob files with `exists`, and a fix for PDF rendering of table cells with several cited turns;
  - tests and the updated sample report and formulas doc.
- **Model calls made:** none. The scoring model is a scripted `FakeLLM` everywhere.
- **Review:** TODO - the author and a teammate confirm they have read and can explain every file before relying on it.
- **Not verified:** the markers, validity rules and confidence weights are untuned guesses; no real model reply has been scored through the pipeline.
