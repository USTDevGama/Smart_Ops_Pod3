# 2026-11-12 - model key: Key Vault mode in the deploy, blank key handling, rejection logs

- **Tool:** Claude Code (running inside VS Code).
- **Account:** TODO - the committer fills in the work account used.
- **What was shared:** this repository's own code (`app/config.py`, `app/llm/provider.py`, `app/llm/vault.py`, the deploy workflow and its docs) and the reason code the gateway returned (HTTP 401, `token_not_found_in_db`). No keys, vault secrets or `.env` contents were shared or written down.
- **What came back:** the deploy workflow can run in Key Vault mode (all five settings or none, with the key line left out of `.env` in vault mode); a blank `PODC_ANTHROPIC_API_KEY` or client secret now counts as unset; the provider logs when a key is rejected (reason only, never the key); a warning-only "Model key check" step after the deploy; `deploy/.env.example`, the runbook and tests (config, provider logging, and the workflow's shell steps against stub commands).
- **Review:** TODO - the committer and a teammate confirm they have read and can explain every file before relying on it.
- **Known gaps to check by a person:**
  - Key Vault mode failed its first run inside the container: the model-key check warned `vault login failed (ConnectError)`. A stage-by-stage test from inside the container (DNS, TCP, TLS with the system store, TLS with `httpx`'s own list) showed only the last one failing with `certificate verify failed`: the proxy re-signs Azure's login and the vault client does not read the system store. The follow-up sets `SSL_CERT_FILE` and `REQUESTS_CA_BUNDLE` to the system bundle in the image. That `httpx` honours the variable was confirmed in its source and by pointing it at a missing file; the fix itself has not run in a container yet.
  - The vault error now includes the connection's own message for a failed connection (not for other errors); it comes from the socket and TLS layers and carries no request content, which is covered by a test.
  - The workflow's shell steps were run against stub `docker` and `sleep` commands, not on the runner.
  - The Azure client secret has an expiry date; when it passes, every model call fails. Someone has to own that renewal.
  - Whether the gateway key will keep being rotated, and whether the vault secret is always updated with it, is not known; vault mode only helps if it is.
