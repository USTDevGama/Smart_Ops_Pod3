# 2026-11-06 - agent redesign to one call per turn (Shubhra)

- **Tool:** Claude Code (running inside VS Code).
- **Account:** TODO - fill in the work account used.
- **What was shared:**
  - this repo's code and its branches (read from a local checkout);
  - the BRD and TDD text;
  - the architect's two new files (the sample project proposal and `proposal_challenge_points.json`) and the program's **confidential seed pack** (persona, scenarios, known-answer cases), read from local folders outside this repo so the agent could be designed and checked against them. **Nothing from them is committed:** the tests use made-up personas, scenarios, documents and answers, and the opt-in eval reads the pack from `PODC_SEED_DIR` at run time.
  - No real trainee data.
  - **Credentials were shared with the tool:** the architect's Azure credentials (a service-principal client secret, and later a Foundry API key and endpoint) were pasted into the conversation so the agent could be run against the project's model. They are not in any committed file. TODO: confirm with the TPM that this tool is approved for that, and rotate them if it is not (the README lists this as an open question).
- **What came back and where it went:** a rewrite of `app/agent/` for the new contract (`llm_engine.py`, `prompts.py`, `context.py`, `drafts.py`, `validate.py`, `errors.py`; `escalation.py` and `grounding.py` removed), the `get_engine()` switch in `app/agent/engine.py`, the tests `tests/test_agent_*.py` and `tests/agent_fixtures.py`, and `docs/agent-architecture.md`.
- **Review:** TODO - the author and a teammate confirm they have read and can explain every file before relying on it.
- **Model calls made:** later the same day the agent was run against the project's Azure-hosted Claude deployment (Claude Sonnet 5) with credentials the architect shared. The prompts contained the architect's sample proposal, the seed persona and scenarios (fictional practice data) and the repo's made-up resume, and a few made-up trainee answers. The key was kept in a scratch file outside the repo and deleted afterwards; it is not in any committed file. TODO: confirm with the TPM that this endpoint is an approved place for the seed pack and the architect's files.
- **Not verified:** only a handful of real conversations have been run (see `docs/agent-architecture.md`, "First run against a real model"); nothing has been checked at the real number of scenarios.
