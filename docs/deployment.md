# Deploying Pod C to the shared server

Pod C's backend runs as two containers from one image (the API and a Celery worker), started with Docker Compose by a GitHub Actions workflow on the server's own runner. PostgreSQL, Redis and the Docker network are shared with the other pods; this stack does not create or store them. There is **no UI** in this deployment: a common UI for all pods comes later. The Streamlit UI is still in the compose file under the `ui` profile for anyone who starts it by hand.

Files: `Dockerfile`, `deploy/compose.prod.yml`, `deploy/.env.example`, `.github/workflows/deploy.yml`.

```
push to main -> runner "pod-c-mycloud" (label podc) -> tests -> image pod-c-app:<sha>
  -> alembic upgrade head -> docker compose up -d (project pod-c) -> health check

  pod-c-api    FastAPI :8000  (not published; reachable on shared-services as pod-c-api)
  pod-c-worker Celery, queues ingest and assess
  both: shared-postgres:5432 (database podc), shared-redis:6379, volume pod-c-storage at /app/storage
  both: https://llmproxy.ustdev.com/  (model claude-sonnet-5-5-hree)
```

## What the workflow does
It runs on every push to `main` (or by hand: Actions, "Deploy POD C", Run workflow), on a runner labelled `podc`. Only one run goes at a time. If a run is stuck in the queue (for example it asks for a label no runner has), every later run waits behind it as `pending`: cancel the stuck one.

| Step | What happens |
|---|---|
| Checkout | A plain `git fetch` of the pushed commit with the job's own read-only token, **not** the `actions/checkout` action. That action is downloaded from `codeload.github.com`, which the company proxy blocks from the VM (the run stopped at "Set up job" with `Access denied`). Git talks to `github.com`, which works. The token is never written to `.git/config`, and the reused workspace is cleaned. Do not add a `uses:` step for another action without checking it can be downloaded from the VM. |
| Checks | Docker, the `shared-services` network and the `pod-c-storage` volume must exist. The deploy folder is created if the runner user may, and `certs/corp-root.crt` must be in it. A missing one fails the run at once, before any build. |
| Test and build | Copies the proxy's root certificate into the build, builds the test image and runs `pytest` inside it, then builds the runtime image tagged with the short commit id. |
| Install | Copies `compose.prod.yml` to the deploy folder and writes `.env` there (mode 600) from the GitHub secrets and variables below. |
| Migrate and start | `alembic upgrade head`, then `docker compose up -d`. |
| Verify | Up to 20 tries: the API container is healthy, `/readyz` answers inside it (so the database is reachable) and the worker answers a Celery ping (so Redis is reachable). On success the tag goes to `.last_good_tag`. On failure it prints the logs, starts the last good tag again if there is one, and fails the run. Database migrations are not rolled back. |
| Clean up | Keeps the three newest `pod-c-app` tags and the last good one; only our own image is touched. |

The deploy folder is `/data/Smart_Ops_Pod3/deploy` unless the repository variable `DEPLOY_DIR` says otherwise. It holds, on the server only: `compose.prod.yml`, `.env`, `.last_good_tag` and `certs/corp-root.crt`. None of these is in git.

## Names
| Name | Where | Why |
|---|---|---|
| `podc` | runner label; Postgres database and role | what the runner and the database were created with |
| `pod-c`, `pod-c-app`, `pod-c-storage` | Compose project, image, Docker volume | the volume already exists on the server under this name, and the workflow checks for it. Renaming it means creating a new volume first |

## One-time setup on the server
| What | Detail | Who |
|---|---|---|
| Runner as a service | `cd /data/Smart_Ops_Pod3/actions-runner-pod-c && sudo ./svc.sh install localadmin && sudo ./svc.sh start && sudo ./svc.sh status`. Pod D's runner is a service too; the VM logs idle shells out, which would stop a runner started with `./run.sh`. Do this last: once online it takes the waiting run at once | server admin |
| Corporate root certificate | `/data/Smart_Ops_Pod3/deploy/certs/corp-root.crt`: one PEM root certificate (`CN = Zscaler Root CA`). It is used only while building the image, because `files.pythonhosted.org` is re-signed by the company proxy. The model gateway presents a public DigiCert chain and needs no certificate. Check a candidate with `openssl s_client -connect files.pythonhosted.org:443 -servername files.pythonhosted.org -CAfile <file>` (want `Verify return code: 0 (ok)`) | us |
| Storage volume owner | `pod-c-storage` was created root-owned, and the container user is 10001. Run once: `docker run --rm -v pod-c-storage:/v --entrypoint chown postgres:16-alpine 10001:10001 /v`. Without it the app falls back silently to the container's `/tmp` (look for `blob folder ... cannot be written` in the API log) | us |
| Docker network and volume | `shared-services` and `pod-c-storage` already exist | done |
| PostgreSQL | database `podc` and role `podc` already exist on `shared-postgres`; the password is not in git | server admin |
| Redis | `shared-redis` is shared. Run `docker exec shared-redis redis-cli INFO keyspace` and make sure database numbers 0 and 1 are not used by another pod; change `PODC_REDIS_URL` and `PODC_CELERY_BROKER_URL` in the workflow if they are | us |

## GitHub secrets and variables
Secrets (Settings, Secrets and variables, Actions). Never put these in git, in a file in the repository, or in a chat. `gh secret set <NAME>` asks for the value at a hidden prompt:

| Secret | Value |
|---|---|
| `PODC_DATABASE_URL` | `postgresql+psycopg://podc:<password>@shared-postgres:5432/podc` |
| `PODC_LLM_PROVIDER` | `anthropic` |
| `PODC_ANTHROPIC_API_KEY` | the model key |
| `PODC_ANTHROPIC_MODEL` | the gateway's model id |
| `PODC_ANTHROPIC_GATEWAY_URL` | the gateway's URL |
| `TRAINEE_DB_URL` | Pod D's PostgreSQL connection URL, stored as a GitHub secret; the assessment job uses it to upsert section-C scores |

Variables (optional; the defaults are shown):

| Variable | Default | Meaning |
|---|---|---|
| `DEPLOY_DIR` | `/data/Smart_Ops_Pod3/deploy` | where the files above live |
| `PODC_ANTHROPIC_THINKING_OFF` | `between_tools` | Claude Sonnet 5.5 rejects `disabled` |
| `PODC_ENV` and `PODC_DEV_AUTH_ENABLED` | `prod` and `false` | see "Login" below. Change them together |

The log level is `PODC_LOG_LEVEL` (default `INFO`).

## Login
There is no real login yet. With `PODC_ENV=prod` and `PODC_DEV_AUTH_ENABLED=false` every API call answers `401 login is not configured yet`, except `/healthz`, `/readyz` and `/api/v1/meta`. That is the intended state until the common UI and Zitadel exist (not built: `app/api/deps.py` still only reads the dev headers). Do not set `PODC_ENV=dev` with dev login on to "test" the deployed API: it lets anyone who can reach the API pick any role without a password, and other pods' containers share the `shared-services` network.

## Secrets on the server's disk
The workflow writes the database URL and the model key into `.env` in the deploy folder and leaves it there (mode 600, owned by the runner user). It has to stay: Compose reads `.env` for every command (`ps`, `logs`, `up`, a manual rollback), not only during a deploy.

What that does and does not change:
- Anyone who can use the runner's account, or who is in the `docker` group, can already read the same values from the running containers (`docker inspect`). Deleting the file would not hide them from those people.
- The file is not readable by other accounts (mode 600).
- Workflows run only on `push` to `main` and by hand. Do not add a `pull_request` trigger: a pull request would then run its code on the self-hosted runner, next to these secrets. The README calls this repository public while GitHub currently shows it private; keep the rule either way.
- `main` deploys on every push and is not protected. Consider requiring pull requests, or trigger by hand only until things are stable.
- When the project ends: delete the deploy folder and rotate the database password and the model key.

A safer later step is to keep only the Azure client secret in `.env` and let the app fetch the model key from the Key Vault at start-up (`PODC_AZURE_*`, already supported). A static key in a GitHub secret goes stale when the key is rotated.

## Day to day
Run these on the server in the deploy folder:
```
cd /data/Smart_Ops_Pod3/deploy
IMAGE_TAG=$(cat .last_good_tag) docker compose -p pod-c -f compose.prod.yml ps
IMAGE_TAG=$(cat .last_good_tag) docker compose -p pod-c -f compose.prod.yml logs --tail=100 api
IMAGE_TAG=$(cat .last_good_tag) docker compose -p pod-c -f compose.prod.yml logs --tail=100 worker
```
The API log shows `llm call purpose=... Ns` for each model call, and `agent ...` / `scoring attempt ...` lines carry the reason code when a call fails (for example `the model call failed (HTTP 403)`).

## Known gaps
- Real login (Zitadel) and the common UI are not built.
- Before enabling Pod D sync, Zitadel auth must map the verified trainee identity to the existing Pod D `trainees.trainee_id` and store that ID as the session owner reference. Never use an untrusted UI-supplied ID.
- Nothing here was run on the server when it was written: the first workflow run is the real test (`docker compose config`, the image build including the certificate step, the migration, the health check).
- The server's root disk (where Docker keeps images, build cache and the volume) was 75% full with about 8 GB free. The workflow removes only our own old tags; build cache is shared with the other pods and is not pruned. Tell the architect.
- Shell settings on the shared `localadmin` account export `SSL_CERT_FILE` and `REQUESTS_CA_BUNDLE` for login shells. Run test commands with `env -u SSL_CERT_FILE -u REQUESTS_CA_BUNDLE`. The runner service does not read them.
