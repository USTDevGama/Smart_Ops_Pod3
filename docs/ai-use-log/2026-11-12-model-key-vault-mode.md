# 2026-11-12 - model key: Key Vault mode in the deploy, blank key handling, rejection logs

- **Tool:** Claude Code (running inside VS Code).
- **Account:** TODO - the committer fills in the work account used.
- **What was shared:** this repository's own code (`app/config.py`, `app/llm/provider.py`, `app/llm/vault.py`, the deploy workflow and its docs) and the reason code the gateway returned (HTTP 401, `token_not_found_in_db`). No keys, vault secrets or `.env` contents were shared or written down.
- **What came back:** the deploy workflow can run in Key Vault mode (all five settings or none, with the key line left out of `.env` in vault mode); a blank `PODC_ANTHROPIC_API_KEY` or client secret now counts as unset; the provider logs when a key is rejected (reason only, never the key); a warning-only "Model key check" step after the deploy; `deploy/.env.example`, the runbook and tests (config, provider logging, and the workflow's shell steps against stub commands).
- **Review:** TODO - the committer and a teammate confirm they have read and can explain every file before relying on it.
- **Known gaps to check by a person:**
  - Key Vault mode has not run inside a container: the vault client (plain `httpx`) must reach Azure AD and the vault from there. It worked from the VM itself.
  - The workflow's shell steps were run against stub `docker` and `sleep` commands, not on the runner.
  - The Azure client secret has an expiry date; when it passes, every model call fails. Someone has to own that renewal.
  - Whether the gateway key will keep being rotated, and whether the vault secret is always updated with it, is not known; vault mode only helps if it is.
