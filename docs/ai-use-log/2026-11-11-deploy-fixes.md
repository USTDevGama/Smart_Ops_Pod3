# 2026-11-11 - deployment fixes (backend-only deploy, health check, build-time CA, logging)

- **Tool:** Claude Code (running inside VS Code).
- **Account:** TODO - the committer fills in the work account used.
- **What was shared:** this repository's own deploy files (`Dockerfile`, `deploy/compose.prod.yml`, `deploy/.env.example`, `.github/workflows/deploy.yml`) and, from the shared server, names and certificate subjects only (the Docker network, volume, database and role names; the issuer names of the TLS chains). No keys, passwords, tokens or `.env` contents were shared or written down.
- **What came back:** a fixed API health-check path; a backend-only compose file (UI behind a profile, unique API alias on the shared network); the company proxy's root certificate trusted at image build time (not committed); a deploy folder on `/data` outside the checkout with a pre-check; a health check that tests the API, the database and the worker instead of a UI port; a `.last_good_tag` rollback; cleanup of old image tags; app logging and the model's reason code in the engine and scorer logs (with tests); `docs/deployment.md` and a README pointer.
- **Review:** TODO - the committer and a teammate confirm they have read and can explain every file before relying on it.
- **Known gaps to check by a person:**
  - Nothing here has run on the server or been checked with `docker compose config` or `docker build`: the changes were read through, and the YAML and the workflow's shell steps were run against stub commands only.
  - The rollback tag file name is modelled on Pod D's `.last_good_tag`; Pod D's workflow itself was not seen.
  - Whether the `update-ca-certificates` step is enough for `pip` inside the build is not known until the first run.
  - An earlier diagnosis in this work (that the model gateway was being re-signed by the proxy) was wrong: the failures came from `SSL_CERT_FILE` being set in the shared shell profile. The gateway needs no certificate.
