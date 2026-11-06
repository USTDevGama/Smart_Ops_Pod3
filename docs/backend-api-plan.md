# Pod C backend: scope and API plan

## Context
The scaffold is pushed. The team then narrowed what we build next:
- **Kedar** owns the ingestion work (reading the uploaded files, OCR) and the **UI**.
- **Shubra** owns the **agent**: how one client reply is produced. It is not yet decided whether that is LangGraph or a plain LLM call with a prompt (LangChain), so our code must not depend on that choice.
- **Disha** owns scoring, review and reports. We only list placeholder endpoints for those.
- **We** build the backend APIs and their logic: settings, the two uploads, sessions, and the chat plumbing (storing turns, limits, safety checks). We call the agent through a small fixed interface.
- These tables are **not needed now** and are not in the schema: `app_user`, `audit_log`, `llm_call_log`, `assessment`, `assessment_evidence`, `review`, `report`. The scoring-profile setting is gone too; scoring will add them back when it is built.

The design still holds: one LLM call per chat turn, plain code enforces the rules, no RAG, trainee text is treated as data, nothing important lives only in Redis.

## What the architect call (05-Nov) decided
- The trainee uploads **only a profile (resume)**: a plain upload, 1 to 3 pages.
- The **demand** (what the project needs, from the Gama team) is a document an **admin uploads**. It is master data: one demand serves everyone (the newest one that is ready).
- Both documents are short, so there is **no chunking and no citations**. The pipeline reads each file and whatever it extracts is saved as JSON in the row's `content` column; the agent receives it as it is.
- **Scenarios are not configured by hand.** The whole dataset is loaded once with an import endpoint, and the agent picks scenarios and the level of questioning itself.
- **Personas stay configurable** (each client has its own escalation ladder).
- A chat **ends only at `max_turns`** (plus `grace_turns` while answers improve), or when someone ends it.

## 1. Database
Five tables: `config_version`, `profile`, `demand_document`, `session`, `turn`. One initial migration creates them (nothing is deployed yet). `session.trainee_ref` and `profile.owner_ref` are plain text: the login user (`X-Dev-User` for now). See [data-model.md](data-model.md).

## 2. Shared plumbing
| Piece | File | What |
|---|---|---|
| Error format | `app/api/errors.py` | every error is `{type, title, status, detail}` |
| Dependencies | `app/api/deps.py` | `get_db`, `get_llm`, `can_see` (trainees see their own rows, admins all), `paging` |
| File storage | `app/storage.py` | `BlobStore` with `save`, `read`, `delete`; `LocalBlobStore` under `PODC_BLOB_DIR` |
| Upload checks | `app/ingest/uploads.py` | size (default 10 MB, else 413), empty (400), and extension **and** first bytes must agree for PDF, DOCX or TXT (else 415) |
| Job dispatch | `app/workers/dispatch.py` | `enqueue_profile_ingest` and `enqueue_demand_ingest`; with `PODC_INGEST_INLINE=true` they run inside the request (no Redis needed locally) |

## 3. API (all under `/api/v1`)
Roles are `trainee`, `admin` and `integrator`, sent as dev headers for now.

### 3.1 Settings (`app/api/admin_config.py`)
Kinds: `persona` and `scenario`. A body is validated with `PersonaConfig` or `ScenarioConfig`. Only personas can be created, edited and published by hand (other kinds answer 422); scenarios are only loaded with the import endpoint, and can be read.
| Endpoint | Who | Does |
|---|---|---|
| `GET /personas` | trainee, admin | the **published** ones, so a trainee can start a session |
| `GET /admin/config/{kind}` | admin | keys with all their versions and status (persona or scenario) |
| `POST /admin/config/persona` | admin | new key at version 1 as `draft`; 409 if the key exists |
| `POST /admin/config/persona/{key}/versions` | admin | new draft version (max + 1), copied from the latest unless a body is given |
| `GET /admin/config/{kind}/{key}/versions/{n}` | admin | one version |
| `PUT /admin/config/persona/{key}/versions/{n}` | admin | edit a **draft** only; 409 otherwise |
| `POST /admin/config/persona/{key}/versions/{n}/publish` | admin | draft becomes published; the previously published version becomes retired |
| `POST /admin/scenarios/import` | admin | loads the whole scenario dataset in one go (same shape as the seed file, `{"scenarios": [...]}`), published straight away. A new id is created, a changed one becomes the next version, an identical one is left alone, so sending the same file again is safe |

Invalid settings give 422 with the reasons. Two admins saving at once is caught by the unique (kind, key, version_no) constraint and answers 409.

### 3.2 Profile (trainee) and demand document (admin): the two uploads
The endpoints and the glue are ours. Reading the file is Kedar's.
| Endpoint | Who | Does |
|---|---|---|
| `POST /profiles` (multipart `file`) | trainee, admin | upload checks above; the same file again by the same owner returns the existing profile (200); otherwise stores the file, creates the row `queued`, queues the ingest job and returns **202** |
| `GET /profiles/{id}` | owner, admin | status, error, and `content` when ready. The UI polls this. 404 for other people's rows |
| `GET /profiles` | owner, admin | own list (admin: all, filter `owner_ref`) |
| `DELETE /profiles/{id}` | owner, admin | 409 if a session uses it; else removes the file and row |
| `POST /admin/demand` (multipart `file`) | admin | same as the profile upload; the same file again returns the existing document (200) |
| `GET /admin/demand`, `GET /admin/demand/{id}` | admin | list; one document with status, error and `content` |
| `DELETE /admin/demand/{id}` | admin | 409 if a session uses it; else removes the file and row |

**Hand-off to Kedar (done).** `ingest_profile(profile_id)` and `ingest_demand(demand_id)` (in `app/workers/tasks.py`) set `status` to `extracting`, read the file, save what they extract as JSON in the row's `content`, and finish `ready`, or `failed` with `error`. The agent gets `content` as it is. The real reading is in `app/ingest/pipeline.py` (with `extract.py`, `pdf_text.py`, `docx_text.py`): text only, no OCR, `content = {"text": "<markdown>"}`. TXT, DOCX and PDF are read; a scanned PDF or a corrupt file fails with a fixed message that never contains the file's text. A storage or database hiccup is retried (3 times, with backoff): the row goes back to `queued` between tries and ends `failed` if the last try fails. `tests/test_ingest_queue.py` runs upload, dispatch, the Celery task and the status together, without a broker.

### 3.3 Sessions and chat (`app/sessions/`)
Two layers keep us independent of how Shubra builds the agent:
- **Ours, the chat service** (`app/sessions/`): endpoints, loading and saving turns, idempotency, the turn limit, a hard clamp on the escalation level, ending the session. It does not import an agent framework (a test checks this).
- **Shubra's, the turn engine** (`app/agent/`): given a context, return the reply.

The interface is in `app/agent/engine.py`:
```python
class TurnEngine(Protocol):
    def opening(self, ctx: SessionContext) -> TurnOutput: ...
    def respond(self, ctx: SessionContext, answer: str) -> TurnOutput: ...
```
`SessionContext` holds the persona, `demand` and `profile` (the extracted JSON of each), **all** published scenarios, previous turns, current level and turns used. `TurnOutput` is in `app/schemas/conversation.py` (evaluation and reply). The engine is chosen in `get_engine()`. Until the real one lands, `PlaceholderEngine` (`app/agent/placeholder.py`) answers with canned logic and **no LLM**, so every endpoint works and is tested.

| Endpoint | Who | Does |
|---|---|---|
| `POST /sessions` | trainee, admin | body `{persona_key, profile_id}`. Uses the latest **published** persona (404 if none) and the newest ready demand document (409 if none, or if no scenarios are loaded). The profile must be the caller's and `ready` (409 if not). The client's opening message is saved as turn 0 |
| `GET /sessions`, `GET /sessions/{id}` | owner, admin | list (filter `status`; admin `trainee_ref`); detail with turns, `demand_id`, current level, `turns_used`, `max_turns`. Only admins see each answer's `evaluation` |
| `POST /sessions/{id}/turns` | owner | body `{content}`, header `Idempotency-Key` (required). Replies as a server-sent event stream: `message`, then `done` |
| `POST /sessions/{id}/end` | owner, admin | ends the session (`trainee_ended`, or `admin_ended` when an admin ends someone else's). Repeating it is harmless. Calls the no-op `on_session_ended` hook where scoring plugs in |

**A turn:**
1. The session must be the caller's and active (404 / 409).
2. If this `Idempotency-Key` was already used, return the stored reply; nothing is asked or saved again.
3. Build the `SessionContext` from the database and call `engine.respond`. Any error gives 502 and **nothing is saved**, so a failed reply never uses up a turn.
4. Clamp the level: it moves at most one step from the previous level and stays within 1 to the persona's top step. The engine's own escalation logic is Shubra's; this only guarantees the rule.
5. Save the trainee turn (with its evaluation) and the client turn in one transaction. Two simultaneous sends are stopped by the unique (session_id, idx) constraint (409).
6. End the session if the trainee has used `max_turns` (plus `grace_turns` only while answers are improving), reason `turn_cap`.
7. Reply with `message` (the client's turn) then `done` (`level`, `turns_used`, `ended`, `end_reason`, `replayed`). The reply is sent when ready, not word by word; real token streaming would need the engine to support it and is a later change.

`max_turns` counts trainee messages (the program's open question: messages or exchanges).

### 3.4 Planned (Disha's area): 501 for now
Listed in `docs/openapi.yaml` so the UI can code against the paths; each answers 501 in the standard shape until built: `GET /sessions/{id}/assessment`, `GET /admin/review-queue`, `POST /admin/assessments/{id}/review`, `POST /admin/assessments/{id}/rescore`, `GET /assessments/{id}/report`, `GET /integration/signals`. Remove a line from `app/api/planned.py` when the real endpoint lands.

### 3.5 Already built
`GET /healthz`, `/readyz`, `/api/v1/meta`.

## 4. Who builds what
| Owner | Work |
|---|---|
| Dev D | the schema migration, shared plumbing, later the real LLM provider and background-job retries and schedules |
| Dev A | profile and demand upload endpoints and glue |
| Dev B | sessions and chat plumbing, the `TurnEngine` interface |
| Dev C | settings endpoints |
| Kedar | real ingestion (reading the files, OCR) and the UI |
| Shubra | the real turn engine behind `TurnEngine` |
| Disha | scoring, review, reports and the Pod D feed |

## 5. Still to do
- The real ingest and the real turn engine (both behind the interfaces above).
- Scoring, review, reports, the Pod D feed, and their tables.
- Background-job retries, the schedule for the stuck-job sweeper, and the 30-day deletion job.
- The real LLM provider once API keys arrive.
- Sandbox test chat for admins; word-by-word reply streaming.
- Real login (the headers are a stand-in).

## 6. Assumptions to confirm
- Kedar writes the real `ingest_profile` and `ingest_demand` bodies and decides the shape of `content`; we own the endpoints around them.
- Shubra agrees to the `TurnEngine` interface and the `SessionContext` fields (the demand and profile arrive as the extracted JSON).
- The engine decides escalation from answer quality; the service only enforces the one-step limit and the turn limit.
- Whether the scenario dataset should live in our table (as now) or in the agent's own store.
