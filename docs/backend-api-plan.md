# Pod C backend: trimmed scope and API plan

## Context
The scaffold is pushed. The team then narrowed what we build next:
- **Kedar** owns the ingestion work (parsing, OCR, the brief) and the **UI**.
- **Shubra** owns the **agent**: how one client reply is produced. It is not yet decided whether that is LangGraph or a plain LLM call with a prompt (LangChain), so our code must not depend on that choice.
- **Disha** owns scoring, review and reports. We only list placeholder endpoints for those.
- **We** build the backend APIs and their logic: settings, proposals, sessions, and the chat plumbing (storing turns, limits, safety checks). We call the agent through a small fixed interface.
- These tables are **not needed now** and were dropped in migration `0002`: `app_user`, `audit_log`, `llm_call_log`, `assessment`, `assessment_evidence`, `review` (and `report`, which only pointed at `assessment`). The scoring-profile setting and `session.scoring_profile_version_id` were dropped too; scoring will add them back when it is built.

The earlier design still holds: one LLM call per chat turn, plain code enforces the rules, no RAG, trainee text is treated as data, nothing important lives only in Redis.

## 1. Database trim (migration 0002)
| Change | Detail |
|---|---|
| Dropped 7 tables | `app_user`, `assessment`, `assessment_evidence`, `review`, `report`, `llm_call_log`, `audit_log` |
| `session.trainee_id` becomes `trainee_ref` | plain text: the login user (`X-Dev-User` for now) |
| `proposal.owner_id` becomes `owner_ref` | same |
| `session.scoring_profile_version_id` | dropped |
| Scoring-profile settings | removed from `ConfigKind`; existing rows deleted by the migration. `ScoringConfig` stays in `app/schemas/config.py` for later |
| Existing data | the new text columns are filled from `app_user.idp_sub` before the old columns are dropped. Uses batch mode so it also runs on SQLite. One-way: no downgrade |

Left with 5 tables: `config_version`, `proposal`, `proposal_segment`, `session`, `turn`. See [data-model.md](data-model.md).

## 2. Shared plumbing
| Piece | File | What |
|---|---|---|
| Error format | `app/api/errors.py` | every error is `{type, title, status, detail}` |
| Dependencies | `app/api/deps.py` | `get_db`, `get_llm`, `can_see` (trainees see their own rows, admins all), `paging` |
| File storage | `app/storage.py` | `BlobStore` with `save`, `read`, `delete`; `LocalBlobStore` under `PODC_BLOB_DIR` |
| Job dispatch | `app/workers/dispatch.py` | `enqueue_ingest(proposal_id)`; with `PODC_INGEST_INLINE=true` it runs the ingest inside the request (no Redis needed locally) |

## 3. API (all under `/api/v1`)
Roles are `trainee`, `admin` and `integrator`, sent as dev headers for now.

### 3.1 Settings (`app/api/admin_config.py`)
Kinds: `persona` and `scenario`. A body is validated with `PersonaConfig` or `ScenarioConfig`.
| Endpoint | Who | Does |
|---|---|---|
| `GET /personas`, `GET /scenarios` | trainee, admin | the **published** ones, so a trainee can start a session |
| `GET /admin/config/{kind}` | admin | keys with all their versions and status |
| `POST /admin/config/{kind}` | admin | new key at version 1 as `draft`; 409 if the key exists |
| `POST /admin/config/{kind}/{key}/versions` | admin | new draft version (max + 1), copied from the latest unless a body is given |
| `GET /admin/config/{kind}/{key}/versions/{n}` | admin | one version |
| `PUT /admin/config/{kind}/{key}/versions/{n}` | admin | edit a **draft** only; 409 otherwise |
| `POST .../versions/{n}/publish` | admin | draft becomes published; the previously published version becomes retired |

Invalid settings give 422 with the reasons (for example `min_turns cannot exceed max_turns`). Two admins saving at once is caught by the unique (kind, key, version_no) constraint and answers 409. A sandbox test chat is deferred.

### 3.2 Proposals (`app/ingest/router.py`)
The endpoints and the glue are ours. Reading the file, OCR and the brief are Kedar's.
| Endpoint | Who | Does |
|---|---|---|
| `POST /proposals` (multipart `file`) | trainee, admin | checks size (default 10 MB, else 413) and that the extension **and** first bytes agree for PDF, DOCX or TXT (else 415); the same file again by the same owner returns the existing proposal (200); otherwise stores the file, creates the row `queued`, queues the ingest job and returns **202** |
| `GET /proposals/{id}` | owner, admin | status, error, brief when ready, segment count. The UI polls this. 404 for other people's rows |
| `GET /proposals` | owner, admin | own list (admin: all, filter `owner_ref`) |
| `GET /proposals/{id}/segments` | owner, admin | the numbered chunks, to show the text a client question cites |
| `DELETE /proposals/{id}` | owner, admin | 409 if a session uses it; else removes chunks, file and row |

**Hand-off to Kedar.** `ingest_proposal(proposal_id)` (in `app/workers/tasks.py`) must set `status` to `extracting`, write `proposal_segment` rows, produce a `Brief` (`app/schemas/proposal.py`, every item citing real segment ids), save it on `proposal.brief`, and finish `ready`, or `failed` with `error`. Until then `app/ingest/placeholder.py` stands in: TXT only, one chunk per paragraph, a small brief from the first paragraphs.

### 3.3 Sessions and chat (`app/sessions/`)
Two layers keep us independent of how Shubra builds the agent:
- **Ours, the chat service** (`app/sessions/`): endpoints, loading and saving turns, idempotency, the turn limit, checking `refs`, a hard clamp on the escalation level, ending the session. It does not import an agent framework (a test checks this).
- **Shubra's, the turn engine** (`app/agent/`): given a context, return the reply.

The interface is in `app/agent/engine.py`:
```python
class TurnEngine(Protocol):
    def opening(self, ctx: SessionContext) -> TurnOutput: ...
    def respond(self, ctx: SessionContext, answer: str) -> TurnOutput: ...
```
`SessionContext` holds the persona, scenario, brief (or none), previous turns, current level, open checklist items and turns used. `TurnOutput` is in `app/schemas/conversation.py` (evaluation, reply, refs). The engine is chosen in `get_engine()`. Until the real one lands, `PlaceholderEngine` (`app/agent/placeholder.py`) answers with canned logic and **no LLM**, so every endpoint works and is tested.

| Endpoint | Who | Does |
|---|---|---|
| `POST /sessions` | trainee, admin | body `{persona_key, scenario_key, proposal_id?}`. Uses the latest **published** persona and scenario (404 if none). A proposal must be the caller's and `ready` (409 if not). The client's opening message is saved as turn 0 |
| `GET /sessions`, `GET /sessions/{id}` | owner, admin | list (filter `status`; admin `trainee_ref`); detail with turns, current level, `turns_used`, `max_turns`. Only admins see each answer's `evaluation` |
| `POST /sessions/{id}/turns` | owner | body `{content}`, header `Idempotency-Key` (required). Replies as a server-sent event stream: `message`, then `done` |
| `POST /sessions/{id}/end` | owner, admin | ends the session (`trainee_ended`, or `admin_ended` when an admin ends someone else's). Repeating it is harmless. Calls the no-op `on_session_ended` hook where scoring plugs in |

**A turn:**
1. The session must be the caller's and active (404 / 409).
2. If this `Idempotency-Key` was already used, return the stored reply; nothing is asked or saved again.
3. Build the `SessionContext` from the database and call `engine.respond`. Any error gives 502 and **nothing is saved**, so a failed reply never uses up a turn.
4. Keep only `refs` that are real chunks of this session's proposal.
5. Clamp the level: it moves at most one step from the previous level and stays within 1 to the persona's top step. The engine's own escalation logic is Shubra's; this only guarantees the rule.
6. Save the trainee turn (with its evaluation) and the client turn in one transaction. Two simultaneous sends are stopped by the unique (session_id, idx) constraint (409).
7. End the session if the trainee has used `max_turns` (plus `grace_turns` only while answers are improving), reason `turn_cap`; or if every checklist item is met and `min_turns` is reached, reason `concerns_resolved`.
8. Reply with `message` (the client's turn) then `done` (`level`, `turns_used`, `ended`, `end_reason`, `replayed`). The reply is sent when ready, not word by word; real token streaming would need the engine to support it and is a later change.

`max_turns` counts trainee messages (the program's open question: messages or exchanges).

### 3.4 Planned (Disha's area): 501 for now
Listed in `docs/openapi.yaml` so the UI can code against the paths; each answers 501 in the standard shape until built: `GET /sessions/{id}/assessment`, `GET /admin/review-queue`, `POST /admin/assessments/{id}/review`, `POST /admin/assessments/{id}/rescore`, `GET /assessments/{id}/report`, `GET /integration/signals`. Remove a line from `app/api/planned.py` when the real endpoint lands.

### 3.5 Already built
`GET /healthz`, `/readyz`, `/api/v1/meta`.

## 4. Who builds what
| Owner | Work |
|---|---|
| Dev D | migration `0002`, shared plumbing, later the real LLM provider and background-job retries and schedules |
| Dev A | proposal endpoints and glue |
| Dev B | sessions and chat plumbing, the `TurnEngine` interface |
| Dev C | settings endpoints |
| Kedar | real ingestion (parsing, OCR, brief) and the UI |
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
- Kedar writes the real `ingest_proposal` body; we own the endpoints around it.
- Shubra agrees to the `TurnEngine` interface and the `SessionContext` fields.
- The engine decides escalation from answer quality; the service only enforces the one-step limit and the turn limit.
