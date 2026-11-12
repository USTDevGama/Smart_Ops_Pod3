# Scaffold review guide

> **Out of date in part (2026-11-04).** This guide describes the scaffold as first pushed, with 12 tables. Migration `0002` has since trimmed the database to 5 tables (`config_version`, `proposal`, `proposal_segment`, `session`, `turn`) and the settings, proposal and chat APIs were added. For the current tables read [data-model.md](data-model.md); for the current API read the README and [backend-api-plan.md](backend-api-plan.md). Sections 3, 4 and 7 to 9 below still describe the original 12 tables and the original stubs.

A guided tour of everything built so far, written so the team can review it. It covers every file, the database in depth (all 12 tables, every column, why it exists, example values), the shared data shapes (schemas), and what is real versus placeholder.

**Snapshot:** 64 files, about 1,400 lines of application code, about 640 lines of tests, 63 tests (58 run anywhere, 5 more run when the confidential seed pack is available).

Contents
1. [How the pieces fit](#1-how-the-pieces-fit)
2. [Every file, in one map](#2-every-file-in-one-map)
3. [The database files](#3-the-database-files)
4. [The 12 tables in depth, with example values](#4-the-12-tables-in-depth-with-example-values)
5. [The schemas folder in depth](#5-the-schemas-folder-in-depth)
6. [The rest of the code](#6-the-rest-of-the-code)
7. [The tests: what each file proves](#7-the-tests-what-each-file-proves)
8. [Samples, docs and tooling](#8-samples-docs-and-tooling)
9. [What is real, what is a stub, what is not built](#9-what-is-real-what-is-a-stub-what-is-not-built)
10. [Assumptions and placeholders](#10-assumptions-and-placeholders)
11. [Review checklist](#11-review-checklist)

---

## 1. How the pieces fit
```
  samples/ and the seed pack  --->  app/seed.py  --->  validated by  app/schemas/  (the shapes)
                                                              |
  app/api/  (endpoints)  --->  app/llm/ (AI doorway)          |  used everywhere
  app/workers/ (background jobs)                              v
                         all of it saves to  app/db/  (12 tables)  <---  built by  alembic/
```
- **Tables** (`app/db/models.py`) are what we store. **Schemas** (`app/schemas/`) are what data must look like as it moves around: AI replies, settings, results that leave the system. They are not duplicates. Some table columns hold JSON, and a schema defines what must be inside it.
- **Alembic** (`alembic/`) is the tool that builds the tables in a real database, following the migration file `0001_initial.py`.
- **`FakeLLM`** is a scripted stand-in for the AI, so everything can be built and tested before API keys arrive.

---

## 2. Every file, in one map
Legend: **real** = working code with tests; **stub** = placeholder that raises "not implemented"; **empty** = only a one-line comment.

### Root
| File | What it contains | Status |
|---|---|---|
| `README.md` | what the project is, architecture, owners, getting started with uv, confidential-data rules, working agreements, design rules, glossary | real |
| `pyproject.toml` | project name, Python 3.12+, the 12 runtime libraries, dev libraries (pytest, ruff, jsonschema), lint and test settings, uv settings | real |
| `uv.lock` | the exact version of every library (83 packages), all from public PyPI | generated |
| `Makefile` | shortcuts for install, lint, test, migrate, run, docker up/down (for machines with `make`) | real |
| `docker-compose.yml` | Postgres 16, Redis 7 (no key eviction, so the queue never loses messages) and Adminer, a table viewer on port 8080 | real |
| `.env.example` | every `PODC_*` setting with safe local defaults, plus the optional seed-pack folder | real |
| `.gitignore` | keeps out the virtual environment, caches, `.env`, `*.db`, `storage/` | real |
| `alembic.ini` | tells Alembic where its folder is | real |

### `alembic/` (migrations)
| File | What it contains |
|---|---|
| `env.py` | connects Alembic to our settings: picks the database URL, runs migrations |
| `script.py.mako` | the template Alembic uses when it generates a new migration file |
| `versions/0001_initial.py` | creates all 12 tables, three indexes, and can undo itself (269 lines) |

### `app/`
| File | What it contains | Status |
|---|---|---|
| `main.py` | builds the web app, refuses to start unsafe settings | real |
| `config.py` | all settings from `PODC_*` environment variables | real |
| `seed.py` | loads the confidential seed pack from a local folder and validates it | real |
| `export_openapi.py` | regenerates `docs/openapi.yaml` and `docs/roleplay_result.schema.json` | real |
| `demo_data.py` | loads a made-up example session (the vendor-delay story from section 4) into a local database so every table has rows to look at: `uv run python -m app.demo_data`. Repeatable, and refuses to run outside local and dev. | real |
| `db/base.py`, `models.py`, `session.py`, `__init__.py` | the database layer, see section 3 | real |
| `schemas/enums.py`, `proposal.py`, `conversation.py`, `config.py`, `assessment.py`, `__init__.py` | the shared data shapes, see section 5 | real |
| `llm/base.py`, `fake.py`, `provider.py`, `__init__.py` | the AI doorway, the scripted fake, and an empty slot for the real provider | real, real, stub |
| `api/deps.py`, `health.py`, `__init__.py` | the dev-only fake login with role checks, and three endpoints | real |
| `workers/celery_app.py`, `tasks.py`, `__init__.py` | background-job setup with safe defaults, and four stub jobs | real, stub |
| `ingest/`, `agent/`, `scoring/`, `reports/` | **empty**: one comment each. This is where the feature work goes. | empty |

### `tests/`, `samples/`, `docs/`
Covered in sections 7 and 8.

---

## 3. The database files

### `app/db/base.py` (33 lines): shared building blocks
| Item | What it does | Why |
|---|---|---|
| `Base` | the parent class every table inherits from | SQLAlchemy needs one registry of all tables |
| `JsonType` | a JSON column that is plain JSON on SQLite and JSONB on PostgreSQL. An empty value is saved as a real database NULL (an empty cell), not as the JSON word `null`. | tests run on SQLite, production on Postgres, and JSONB is Postgres's faster and searchable JSON |
| `uuid_pk()` | the `id` column on every table: a random UUID | ids can be created anywhere without clashing, and cannot be guessed in sequence |
| `created_at_col()` | a timestamp that the database fills in automatically | one definition, same on every table |
| `enum_col()` | stores a fixed list of values as short text (up to 32 characters), not as a database enum | adding a new value later needs no migration |

### `app/db/models.py` (233 lines): the 12 tables
One class per table. Each has a comment saying what it is for. Details in section 4.

### `app/db/session.py` (29 lines): connecting
| Function | What it does |
|---|---|
| `get_engine()` | creates the database connection once and reuses it (with a check that the connection is alive) |
| `get_session()` | gives each web request its own database session, closed afterwards |
| `check_database()` | runs `SELECT 1`; used by the `/readyz` endpoint to say "can I reach my database?" |

### `alembic/versions/0001_initial.py` (269 lines): the work order
The instructions that actually create the tables: 12 `create_table` steps in dependency order (people and settings first, then the things that point at them), three indexes, and a `downgrade()` that drops them in reverse. It is hand-written because there was no Postgres to auto-generate against. A test (`test_migrations.py`) proves it produces exactly the schema `models.py` describes. **It is frozen now**: future changes are new files, never edits to this one.

---

## 4. The 12 tables in depth, with example values
All example data below comes from one made-up session, the **vendor-delay** scenario in `samples/`, played by a trainee and reviewed by an admin. Real ids are long random UUIDs. They are shortened here (`U1`, `C1`, `T1`...) so you can follow them from table to table.

How a session fills the tables, in order:
```
 admin saves settings ........ config_version   (C1 persona, C2 scenario, C3 scoring)
 people log in ............... app_user         (U1 trainee, U2 admin)
 [optional] proposal upload .. proposal, proposal_segment
 session starts .............. session
 each chat message ........... turn             (+ llm_call_log for each AI call)
 session ends, scoring runs .. assessment, assessment_evidence
 admin reviews ............... review           (+ audit_log)
 report built ................ report
```

### 4.1 `app_user`: who is using the system
**Purpose:** ownership and access control. It lets us say "this trainee's session", without storing names or passwords (the company login system holds those).
**Why it exists:** every proposal, session and review points at a person. `trainee_ref` lets results leave the system without a name.

| Column | Type | Why it is there | Example (U1 trainee) | Example (U2 admin) |
|---|---|---|---|---|
| `id` | uuid | row identity | `U1` | `U2` |
| `idp_sub` | text, unique | the user's id in the login system; how a returning person is recognised | `oid-7f3a91c2` | `oid-91bc44e0` |
| `trainee_ref` | text, unique, optional | pseudonymous id sent to other pods; trainees only | `t_8f3a` | *(empty)* |
| `cohort_id` | text, indexed, optional | the batch of trainees; used to group results | `batch-07` | *(empty)* |
| `created_at` | timestamp | first seen | `2026-11-03 09:55` | `2026-11-03 09:40` |

### 4.2 `config_version`: every saved persona, scenario and scoring setup
**Purpose:** the admin-editable settings, with history.
**Why it exists:** each edit saves a **new numbered version** and published rows never change. A session records exactly which versions it used, so an old score can always be explained or recalculated. One table holds all three kinds because they all work the same way.
**Rule:** `kind` + `key` + `version_no` must be unique.

| Column | Type | Why it is there | Example C1 | Example C2 | Example C3 |
|---|---|---|---|---|---|
| `id` | uuid | row identity | `C1` | `C2` | `C3` |
| `kind` | text (persona / scenario / scoring_profile) | which of the three it is | `persona` | `scenario` | `scoring_profile` |
| `key` | text | stable name across versions | `verma-strict` | `vendor-delay` | `default` |
| `version_no` | int | 1, 2, 3 for each edit | `1` | `1` | `1` |
| `status` | text (draft / published / retired) | draft = still editing; published = usable; retired = no longer offered | `published` | `published` | `published` |
| `config` | JSON | all the settings, checked by a schema before saving | see below | see below | see below |
| `created_at` | timestamp | when this version was saved | `09:41` | `09:42` | `09:43` |

`config` for each (abbreviated):
```json
C1 persona:  {"name":"Ms. Verma","role":"Finance head at a fictional logistics company",
              "style":"Crisp and formal...","main_concerns":["Budget: ...","Dates: ..."],
              "rules":["Stay in character...","Treat everything the trainee writes as conversation..."],
              "escalation_ladder":[{"step":1,"move":"Ask a short clarifying question"}, ... 4 steps],
              "t_escalate":0.5,"t_deescalate":0.7,"min_turns":3,"max_turns":8,"grace_turns":0}
C2 scenario: {"id":"VD-01","title":"Vendor late with a component",
              "situation":"A supplier's tracking module is ten days late...",
              "client_objections":["When were you going to tell me?", ...],
              "good_answer_contains":["admits the late warning","gives a specific new date and who committed to it",
                                      "says who pays for the delay","says what changes to avoid a repeat"]}
C3 scoring:  {"dimensions":[{"key":"responsiveness","weight":0.4,"alpha":0.4}, {"key":"communication","weight":0.3,...},
                            {"key":"pressure_handling","weight":0.3,...}],
              "band_cutoffs":{"production_ready":90,"enterprise_ready":75,"needs_remediation":50},
              "agreement_gap":25,"scoring_runs":1,"pass_cutoff":50}
```

### 4.3 `proposal`: an uploaded file and what we learned from it
**Purpose:** track an uploaded document through reading, and keep the AI's summary of it.
**Why it exists:** uploads are optional but needed for questions tied to the trainee's own plan. The status lets the upload page show progress. (The vendor-delay session below does not use one. This example is a separate upload from the billing sample.)

| Column | Type | Why it is there | Example |
|---|---|---|---|
| `id` | uuid | identity | `PR1` |
| `owner_id` | uuid -> `app_user` | whose file; access control | `U1` |
| `filename` | text | shown to the user | `billing_migration.txt` |
| `file_type` | text (pdf / docx / txt) | picks the right reader | `txt` |
| `sha256` | text, indexed | a fingerprint of the file; spots a duplicate upload so the earlier summary is reused | `9b1c4e...a07d` |
| `blob_uri` | text | where the original file is stored; the file stays out of the database | `storage/9b1c4e.txt` |
| `status` | text (queued / extracting / ready / failed) | what the upload page watches | `ready` |
| `brief` | JSON, optional | the AI's structured summary, empty until `ready` | see below |
| `error` | text, optional | why it failed, if it did | *(empty)* |
| `created_at` | timestamp | also starts the 30-day deletion clock | `2026-11-03 09:50` |

`brief` example:
```json
{"summary":"Six-month, $400k migration of billing to microservices with three teams.",
 "items":[{"kind":"weak_point","text":"Budget breakdown deferred until after approval","segment_ids":["SEG2"]},
          {"kind":"risk","text":"Single payment vendor, contract not signed","segment_ids":["SEG3"]}]}
```

### 4.4 `proposal_segment`: the proposal cut into numbered chunks
**Purpose:** make every part of a proposal citable.
**Why it exists:** the persona may only challenge what the proposal really says. It names the chunk it relied on, and code checks the chunk exists. Each brief item carries chunk ids for the same reason.
**Rule:** `proposal_id` + `seq` is unique. Chunks are deleted with their proposal.

| Column | Type | Why it is there | Example SEG2 | Example SEG4 (scanned page) |
|---|---|---|---|---|
| `id` | uuid | what citations point at | `SEG2` | `SEG4` |
| `proposal_id` | uuid -> `proposal` | parent | `PR1` | `PR1` |
| `seq` | int | order within the proposal | `2` | `4` |
| `page` | int | page number (1 for plain text) | `1` | `2` |
| `kind` | text (text / ocr) | `ocr` = read from an image of text | `text` | `ocr` |
| `text` | text | the chunk | "4. Budget The total budget is $400,000. A detailed breakdown will be shared after approval." | "Vendor contract - draf t pending" |
| `ocr_confidence` | float 0 to 1, optional | how sure the OCR was; empty for normal text | *(empty)* | `0.62` (low, so flagged, not trusted) |

### 4.5 `session`: one roleplay run
**Purpose:** the container for one trainee's conversation, pinning what it ran with.
**Why it exists:** `persona_version_id`, `scenario_version_id` and `scoring_profile_version_id` freeze the exact settings, so the score is reproducible later even after admins edit things. The proposal is optional.

| Column | Type | Why it is there | Example S1 |
|---|---|---|---|
| `id` | uuid | identity | `S1` |
| `trainee_id` | uuid -> `app_user` | who is playing | `U1` |
| `proposal_id` | uuid -> `proposal`, **optional** | a session can run on the scenario alone | *(empty)* |
| `persona_version_id` | uuid -> `config_version` | exact persona used | `C1` |
| `scenario_version_id` | uuid -> `config_version` | exact scenario used | `C2` |
| `scoring_profile_version_id` | uuid -> `config_version` | exact scoring setup used | `C3` |
| `status` | text (active / ended) | is the chat still open | `ended` |
| `end_reason` | text, optional | why it ended: `trainee_ended`, `turn_cap`, `concerns_resolved` (all checklist items covered), `time_limit`, `admin_ended` | `trainee_ended` |
| `started_at` | timestamp | timing | `10:00:00` |
| `ended_at` | timestamp, optional | timing; starts the 30-day deletion clock | `10:06:00` |

### 4.6 `turn`: the chat, one row per message
**Purpose:** the full record of the conversation. **Never edited.** The single most important table.
**Why it exists:** it is the source of truth for scoring, and the thing every piece of evidence points at.
**Rules:** `session_id` + `idx` is unique, so no two messages share a position. `session_id` + `idempotency_key` is unique, so a retried message cannot be saved twice. `escalation_level` must be 1 to 4 or empty.

| Column | Type | Why it is there |
|---|---|---|
| `id` | uuid | what evidence points at |
| `session_id` | uuid -> `session` | parent; deleted with the session |
| `idx` | int | position, starting at 0. The turn limit counts trainee rows. (The result format numbers messages from 1, so result turn = `idx` + 1.) |
| `role` | text (persona / trainee) | who said it. Only trainee rows are scored. |
| `content` | text | the message |
| `escalation_level` | int 1 to 4, optional | how tough the client was in that reply. Persona rows only. It also gives the "current level" without any extra stored state. |
| `refs` | JSON list, optional | proposal chunks the client's question relied on. Persona rows only. |
| `evaluation` | JSON, optional | the AI's judgement of a trainee answer. Trainee rows only. |
| `idempotency_key` | text, optional | de-duplicates retries. Trainee rows only. |
| `created_at` | timestamp | order, time limit, how long the trainee took to answer |

The five rows of the example session:
| `idx` | role | `content` | `escalation_level` | `evaluation` | `idempotency_key` |
|---|---|---|---|---|---|
| 0 | persona | "Your supplier has not delivered the tracking module. When were you planning to tell me?" | 2 | | |
| 1 | trainee | "We hit a snag with the supplier and are looking at options. I will update you when I know more." | | `{"answer_quality":0.2,"checklist_met":[],"evasive":false,"composure":0.9,"quote":"looking at options","proposed_level":3}` | `k-0001` |
| 2 | persona | "Options is not a plan. Give me a date and tell me what it costs me." | 3 | | |
| 3 | trainee | "I should have escalated on Monday. The supplier now commits to 9 June. We will cover the extra four days of testing ourselves, and I will send you a status every Friday until it ships." | | `{"answer_quality":0.85,"checklist_met":["admits the late warning","gives a specific new date and who committed to it","says who pays for the delay"],"evasive":false,"composure":0.9,"quote":"The supplier now commits to 9 June","proposed_level":2}` | `k-0002` |
| 4 | persona | "Fine. But what is different this time, so I am not here again in a month?" | 3 | | |

Row 4 stays at step 3: easing off needs two good answers in a row, and there has been one.

### 4.7 `assessment`: the suggested mark for a session
**Purpose:** the system's suggested result, before a human decides.
**Why it exists:** a re-score adds a new row (`run_no`) instead of overwriting, so the history stays. `status` shows where it is in the pipeline.
**Rule:** `session_id` + `run_no` is unique.

| Column | Type | Why it is there | Example A1 |
|---|---|---|---|
| `id` | uuid | identity | `A1` |
| `session_id` | uuid -> `session` | which session; deleted with it | `S1` |
| `run_no` | int | 1, 2... for each scoring run | `1` |
| `status` | text (queued / running / needs_review / finalized / failed) | pipeline state | `finalized` |
| `composite` | float, optional | overall mark 0 to 100 | `73.8` |
| `band` | text, optional | the mark as a label | `needs_remediation` |
| `confidence` | text (high / medium / low), optional | how sure the system is, worked out by code | `medium` |
| `dimensions` | JSON | per skill: weight, counted score, AI score, blended score | below |
| `details` | JSON | warnings and the numbers behind confidence | below |
| `created_at` | timestamp | when produced | `10:07` |

`dimensions` and the arithmetic, using the placeholder settings (alpha 0.4):
```json
[{"key":"responsiveness","weight":0.4,"code_score":75,"llm_score":70,"score":72.0},
 {"key":"communication","weight":0.3,"code_score":50,"llm_score":70,"score":62.0},
 {"key":"pressure_handling","weight":0.3,"code_score":100,"llm_score":80,"score":88.0}]
```
- responsiveness: 0.4 x 75 + 0.6 x 70 = 72. Counted score: 3 of 4 checklist items met = 75.
- communication: 0.4 x 50 + 0.6 x 70 = 62. Counted score: 1 of 2 answers had 2+ specifics.
- pressure_handling: 0.4 x 100 + 0.6 x 80 = 88. Counted score: answer quality rose by 0.65 (0.2 to 0.85).
- composite = 0.4 x 72 + 0.3 x 62 + 0.3 x 88 = 28.8 + 18.6 + 26.4 = **73.8**, just under the 75 cutoff, so `needs_remediation`.

`details`:
```json
{"flags":["below_min_turns"],
 "grounding":{"cited":4,"passed":4},
 "code_vs_llm_gaps":{"responsiveness":5,"communication":20,"pressure_handling":20}}
```
Confidence is `medium` because the trainee answered only twice (the persona's minimum is 3). The counted and AI scores never differ by more than 25 points, and all four quotes passed the check.

### 4.8 `assessment_evidence`: one cited quote per row
**Purpose:** the proof behind each point in the mark.
**Why it exists:** `turn_id` is a link to a real message. A finding with no real source **cannot be saved**. This is the BRD's "no made-up findings" rule, enforced in the database itself, not just in code.

| Column | Type | Why it is there |
|---|---|---|
| `id` | uuid | identity |
| `assessment_id` | uuid -> `assessment` | parent; deleted with it |
| `dimension` | text | which skill the quote supports |
| `turn_id` | uuid -> `turn` | the proof |
| `quote` | text | the exact words, checked to be in that message |
| `polarity` | text (positive / negative) | helped or hurt the score |

Example rows for A1:
| `dimension` | `turn_id` | `quote` | `polarity` |
|---|---|---|---|
| responsiveness | T3 (idx 3) | "The supplier now commits to 9 June" | positive |
| responsiveness | T3 | "I should have escalated on Monday" | positive |
| communication | T1 (idx 1) | "looking at options" | negative |
| pressure_handling | T3 | "I will send you a status every Friday" | positive |

### 4.9 `review`: the admin's decision
**Purpose:** the human decision, kept separate from the machine's suggestion.
**Why it exists:** the program requires manual review. The suggested mark and the final mark are different facts, so they live in different tables.

| Column | Type | Why it is there | Example |
|---|---|---|---|
| `id` | uuid | identity | `R1` |
| `assessment_id` | uuid -> `assessment` | what was reviewed | `A1` |
| `reviewer_id` | uuid -> `app_user` | who | `U2` |
| `decision` | text (approve / override) | what they decided | `approve` |
| `final_score` | float | the mark that counts; equals the suggestion when approved | `73.8` |
| `comment` | text, optional | the reason; required when overriding | "Short session, but the recovery is clear." |
| `created_at` | timestamp | when | `10:12` |

### 4.10 `report`: a generated PDF or HTML file
**Purpose:** remember where a generated report is stored.
**Why it exists:** the file lives outside the database (it can be large); this row is just the pointer.

| Column | Type | Why it is there | Example |
|---|---|---|---|
| `id` | uuid | identity | `RP1` |
| `assessment_id` | uuid -> `assessment` | which result it shows | `A1` |
| `format` | text (pdf / html) | file type | `pdf` |
| `blob_uri` | text | where the file is | `storage/reports/A1.pdf` |
| `created_at` | timestamp | when generated | `10:13` |

### 4.11 `llm_call_log`: every call to the AI model
**Purpose:** cost control, debugging, and the per-session cap on calls (default 40).
**Why it exists:** each AI call costs money and time. **It stores no prompt text**, only counts and timings.

| Column | Type | Why it is there | Example 1 | Example 2 |
|---|---|---|---|---|
| `id` | uuid | identity | `L1` | `L2` |
| `ref_id` | uuid, indexed, optional | the session or proposal it belonged to | `S1` | `S1` |
| `purpose` | text | what it was for: `brief`, `opening`, `turn`, `score` | `opening` | `score` |
| `model` | text | which model answered | `claude-sonnet-5-5` | `claude-sonnet-5-5` |
| `prompt_version` | text | which version of our prompt text | `opening-v1` | `score-v1` |
| `tokens_in` / `tokens_out` | int | how much went in and came out (drives cost) | 900 / 40 | 2100 / 380 |
| `latency_ms` | int | how long it took | 1100 | 3200 |
| `status` | text | succeeded or failed | `ok` | `ok` |
| `created_at` | timestamp | when | `10:00:01` | `10:07:02` |

This session made 4 calls: 1 opening, 2 turns, 1 score.

### 4.12 `audit_log`: who did what
**Purpose:** accountability for sensitive trainee data (BRD BR-13).
**Why it exists:** config changes, reviews, report downloads and deletions must be traceable to a person.

| Column | Type | Why it is there | Example 1 | Example 2 |
|---|---|---|---|---|
| `id` | uuid | identity | `AU1` | `AU2` |
| `actor_id` | uuid -> `app_user`, optional | who (empty for system actions such as the nightly purge) | `U2` | `U2` |
| `action` | text | what happened | `config.publish` | `review.approve` |
| `entity_type` | text | what kind of thing it touched | `config_version` | `assessment` |
| `entity_id` | uuid, optional | which one | `C1` | `A1` |
| `detail` | JSON, optional | what changed | `{"version_no":1}` | `{"final_score":73.8}` |
| `created_at` | timestamp | when | `09:41` | `10:12` |

### 4.13 Pod D score handoff
The outgoing result (`RoleplayResult`) is built from the validated assessment and authenticated trainee id. It is upserted into Pod D's `trainee_profiles.trainee_scores` only in production when dev auth is disabled. `samples/results/vendor_delay_result.json` shows the payload before persistence: `trainee_id` plus integer `C_scores` for G06, G08 and G10. Scores map deterministically from criterion points, round half up, and clamp to the live database's 1-5 constraint.

### 4.14 Why we keep these in the database, who uses them, and the intuition

**The intuition: the database is the system's memory.** The web app and the background workers are separate programs. Either can be restarted at any moment, and neither can see the other's variables. Anything that must survive a restart, be shared between them, be shown to a person later, or be proven afterwards has to be written down somewhere they can both read. A row is kept only if it answers one of five needs:

| Need | In plain words | Tables that serve it |
|---|---|---|
| **Continue** | pick the conversation up again after a refresh, crash or restart | `session`, `turn` |
| **Show** | a screen needs it | `proposal`, `session`, `assessment`, `report`, `config_version` |
| **Prove** | every point in a score traces to words someone really said (BRD BR-12), and a human can check | `turn`, `assessment_evidence`, `review` |
| **Reproduce** | explain an old score exactly, even after admins change settings | `config_version`, the version ids pinned on `session`, `assessment.run_no` |
| **Account** | cost, audit trail and deletion on a schedule (BRD BR-13) | `llm_call_log`, `audit_log`, the date columns |

**What we deliberately do not store:** names, passwords, API keys, the text of prompts, the outgoing result as a table of its own (it is built on demand), and values that can be worked out from other rows (the current escalation level comes from the last persona `turn`, so it can never disagree with the chat).

**Will the UI use them?** The UI is parked and none of these screens exist yet. This is what is planned, and which tables each screen would read:

| Who | Screen | Reads |
|---|---|---|
| Trainee | Upload | `proposal` (progress, errors) |
| Trainee | Chat, and "my sessions" | `session`, `turn` |
| Trainee | My result, once released | `assessment`, `review`, `report` |
| Admin | Persona, scenario and scoring editor, with history | `config_version` |
| Admin | Sessions list and filters | `session`, `app_user` |
| Admin | **Review queue** (the main admin screen) | `assessment` (mark, confidence, warnings), `assessment_evidence` + `turn` (click a quote, jump to the message), `review` |
| Admin | Report download | `report` |
| Admin | Audit page | `audit_log` |
| Admin or ops | Cost and call counts | `llm_call_log` |
| Pod D and the TPM (an API, not a screen) | Finalized results | built from `turn` + `assessment` + `review`; only admin-approved results leave |

Some data is never shown to people but must exist for the system to be correct: `idempotency_key` (stops a double-click creating two messages), `sha256` (spots duplicate uploads), `run_no` (keeps re-score history), `prompt_version` and the token counts in `llm_call_log`.

**Table by table: the question it answers, and what breaks without it**
| Table | The question it answers | Who reads it | Without it |
|---|---|---|---|
| `app_user` | "Whose is this?" | every endpoint, to give each person only their own data; the admin lists (by `trainee_ref`, never a name); Pod D (`trainee_ref`, `cohort_id`) | no ownership, no access control |
| `config_version` | "What exactly did Ms. Verma look like when this session ran?" | the settings editor; the chat engine at session start; the scoring job (weights) | edits would silently change old scores; no history; no draft and publish |
| `proposal` | "Is my upload ready, and what did the AI learn from it?" | the upload page (status, error); the chat engine (the brief) | no progress bar; the summary re-computed (and re-paid for) on every duplicate upload |
| `proposal_segment` | "What is 'page 7' exactly?" | the chat engine (cites a chunk); the code that checks citations; the UI could show "from page 1" next to a question | the persona's references could not be verified, so it could invent them |
| `session` | "Which conversation is this, and what did it run with?" | "my sessions" and the admin list; the turn-limit logic; the scoring and deletion jobs | no container for a chat; nothing to reproduce |
| `turn` | "What was actually said?" | the chat screen (history, resume); the review screen (jump to a message); the scoring job (reads the whole chat); the result for Pod D; the turn limit | everything: no transcript, no evidence, no score |
| `assessment` | "What mark is suggested, and how sure are we?" | the review queue (sorted by confidence and warnings); the result for Pod D; the report | nothing for the admin to review; a re-score would overwrite history |
| `assessment_evidence` | "Where does each point in the score come from?" | the review screen (clickable quotes); the report (`[message 4]` plus the quote); the database itself, which refuses a finding with no real source | no proof, and a made-up finding could be saved |
| `review` | "What did the human decide?" | the review screen (approve or override); the gate for what may leave the pod | the machine's suggestion and the human's decision would be mixed up; no accountability |
| `report` | "Where is the PDF?" | the "download report" button | regenerate every time, or lose track of the files |
| `llm_call_log` | "How many AI calls, and what did they cost?" | the cap of 40 calls per session; a cost view; debugging slow or failed calls | no cap enforcement, no cost visibility |
| `audit_log` | "Who changed or saw what?" | the admin audit page; compliance checks | cannot show who published a persona or downloaded a report |

**Retention ties it together.** Because every row carries a date, a nightly job can delete a session's data 30 days after it ends (the job is not written yet). Whether approved results should outlive that, for Pod D, is an open question for the TPM.

---

## 5. The schemas folder in depth
Schemas are Pydantic classes: they check that data has the right shape and ranges before it is used or saved.

### `enums.py`: the fixed lists of values (86 lines)
Used by both the tables and the schemas, so they always agree.
| Enum | Values |
|---|---|
| `Role` | trainee, admin, integrator |
| `ConfigKind` | persona, scenario, scoring_profile |
| `ConfigStatus` | draft, published, retired |
| `FileType` | pdf, docx, txt |
| `ProposalStatus` | queued, extracting, ready, failed |
| `SegmentKind` | text, ocr |
| `SessionStatus` | active, ended |
| `EndReason` | trainee_ended, turn_cap, concerns_resolved, time_limit, admin_ended |
| `TurnRole` | persona, trainee |
| `AssessmentStatus` | queued, running, needs_review, finalized, failed |
| `Confidence` | high, medium, low |
| `Polarity` | positive, negative |
| `ReviewDecision` | approve, override |
| `ReportFormat` | pdf, html |

### `proposal.py`: the uploaded document (37 lines)
| Class | Fields | Rules | Relates to |
|---|---|---|---|
| `Segment` | id, proposal_id, seq, page, kind, text, ocr_confidence | confidence between 0 and 1 | table `proposal_segment` |
| `BriefItem` | kind (claim / assumption / risk / weak_point / inconsistency), text, segment_ids | at least one chunk id, so nothing is claimed without a source | inside `proposal.brief` |
| `Brief` | summary, items | | column `proposal.brief` |

### `conversation.py`: the chat (44 lines)
| Class | Fields | Rules | Relates to |
|---|---|---|---|
| `Evaluation` | answer_quality, checklist_met, evasive, composure, quote, proposed_level | quality and composure 0 to 1; level 1 to 4 | column `turn.evaluation` |
| `TurnOutput` | evaluation, reply, refs | **what the per-message AI call must return** | not stored as is; split into two `turn` rows |
| `Turn` | the fields of a `turn` row | escalation level 1 to 4 | table `turn` |

### `config.py`: admin-editable settings (105 lines)
| Class | What it is | Rules |
|---|---|---|
| `EscalationStep` | one rung of the ladder: `step` (1 to 4), `move` | |
| `PersonaConfig` | name, role, style, main_concerns, rules, escalation_ladder, version label, plus our tuning knobs: t_escalate 0.5, t_deescalate 0.7, min_turns 3, max_turns 8, grace_turns 0 | ladder steps unique and in order; min_turns not above max_turns; t_deescalate not below t_escalate; **ignores unknown extra fields**, since seed files carry bookkeeping fields |
| `ScenarioConfig` | id, title, situation, client_objections, good_answer_contains | at least one objection and one checklist item |
| `EnvironmentSettings` | environment, persona_file, max_turns | the seed pack's stage and prod files |
| `DimensionConfig` | key, label, weight, alpha | weight and alpha 0 to 1 |
| `BandCutoffs` | 90 / 75 / 50 (placeholders) | |
| `ScoringConfig` | dimensions, band cutoffs, agreement gap 25, minimum citation pass rate 0.8, scoring runs 1, pass cutoff 50 | **weights must total 1**; dimension keys unique |

`PersonaConfig`, `ScenarioConfig` and `ScoringConfig` are each stored as JSON in `config_version.config`.

### `assessment.py`: scoring and output (92 lines)
**Inside the system:**
| Class | What it is |
|---|---|
| `Finding` | one cited quote (turn id, quote, positive or negative); becomes an `assessment_evidence` row |
| `LLMDimensionScore` | what the AI returns for one skill: score 0 to 100, reason, findings |
| `ScoringOutput` | the whole scoring reply, a list of those |
| `DimensionResult` | one skill after our checks: weight, counted score, AI score, blended score, only the findings that passed the check |
| `Assessment` | the full suggested result (composite, band, confidence, skills, flags); the table splits the extras into `details` |

**What leaves the system (the program's "roleplay-result" format):**
| Class | What it is | Rules |
|---|---|---|
| `RoleplayResult` | `trainee_id` and `C_scores` for G06, G08 and G10 | Scores map C1+C3 to G06, C2 to G08, C4 to G10, then round weighted points to integer 1-5 |

### `__init__.py` (47 lines)
Re-exports all of the above so other code writes `from app.schemas import PersonaConfig`.

---

## 6. The rest of the code

### `app/config.py`
Settings use `PODC_*` environment variables, except the separate Pod D connection secret `TRAINEE_DB_URL`. `assert_safe_for_env()` refuses to start if the dev fake login is on outside `local` or `dev`.

### `app/seed.py` (37 lines)
Loads the confidential seed pack from the folder in `PODC_SEED_DIR`: `load_persona`, `load_scenarios`, `load_environment_settings`. The pack is never inside this repo.

### `app/llm/`: the AI doorway
| File | Contents |
|---|---|
| `base.py` | `LLMClient` (the interface: `complete` and `stream`), `LLMRequest`, `LLMResponse`, `Message`, `LLMError` |
| `fake.py` | `FakeLLM`: returns scripted replies by purpose, records every request, and in strict mode errors if it runs out of script |
| `provider.py` | `ProviderLLM`: the real provider, **not written yet**; raises "not implemented" |
| `__init__.py` | `get_llm_client()`: `fake` gives `FakeLLM`, anything else gives `ProviderLLM` |

### `app/api/` and `app/main.py`
| File | Contents |
|---|---|
| `main.py` | builds the app and checks settings are safe |
| `api/health.py` | `GET /healthz` (up), `GET /readyz` (can reach the database, otherwise 503), `GET /api/v1/meta` (name, version, capabilities; what the TPM reads on Day 8) |
| `api/deps.py` | the dev-only fake login: reads `X-Dev-User` and `X-Dev-Role` headers; `require_role(...)` blocks the wrong role with 403 and missing or unknown with 401 |

### `app/workers/`
| File | Contents |
|---|---|
| `celery_app.py` | job queue setup: three queues (`ingest`, `assess`, `report`), results never stored in Redis, a job is only removed once finished, a crashed worker's job is redelivered |
| `tasks.py` | four stub jobs, each naming its owner: `ingest_proposal`, `run_assessment`, `render_report`, `sweep_stuck_jobs` |

---

## 7. The tests: what each file proves
63 tests in 10 files.
| File | Tests | What it proves |
|---|---|---|
| `test_schemas.py` | 11 | sample persona, scenario and scoring files are valid; weights must total 1; ladder order and range; extra fields ignored; turn limits; brief items need a source; AI-reply bounds |
| `test_db_models.py` | 8 | exactly the 12 planned tables; each compiles for PostgreSQL; duplicate message positions rejected; escalation 0, 5 and 9 rejected; **evidence pointing at a non-existent turn is rejected**; a session works without a proposal |
| `test_result_contract.py` | — | Pod D payload validation, deterministic score mapping, database upsert shape, and generated JSON schema |
| `test_migrations.py` | 1 | the migration builds exactly the schema the models describe, and undoes cleanly |
| `test_llm_fake.py` | 6 | scripted replies in order; structured replies parsed; wrong shape rejected; strict mode; streaming; the factory |
| `test_api_roles.py` | 3 | admin allowed, trainee forbidden, missing or unknown role unauthorised |
| `test_health.py` | 4 | `/healthz`, `/api/v1/meta`, `/readyz` follows the database, dev login refused in prod |
| `test_workers_and_packages.py` | 8 | owner packages import; safe job defaults; jobs routed to the right queues |
| `test_demo_data.py` | 7 | the example loader fills all 12 tables with the planned row counts, adds nothing when run twice, every evidence quote is really in its message, the mark follows the formula (73.8), the persona cites a real proposal chunk, empty JSON values are saved as real NULLs, and it refuses to run in prod |
| `test_seed_pack.py` | — | **skipped unless `PODC_SEED_DIR` is set.** Checks personas, scenarios, environment settings, and known-answer cases. |

`conftest.py` provides an in-memory SQLite database with foreign keys switched on, so no Postgres or Docker is needed.

---

## 8. Samples, docs and tooling
**`samples/`: made-up, in the shape of the seed pack, with none of its content**
| File | Contents |
|---|---|
| `personas/ms_verma_strict.json` | "Ms. Verma", finance head at a fictional logistics company; 4-step ladder |
| `scenarios/vendor_delay.json` | VD-01: a supplier module ten days late; 3 objections; 4-item checklist |
| `results/vendor_delay_result.json` | an example Pod D payload with trainee id and goal scores |
| `scoring/default.json` | three dimensions, weights 0.4 / 0.3 / 0.3, alpha 0.4 (all placeholders) |
| `proposals/billing_migration.txt` | a short proposal with deliberate weak points |

**`docs/`**
| File | Contents |
|---|---|
| `data-model.md` | a shorter table-by-table reference |
| `scaffold-review.md` | this file |
| `openapi.yaml` | the API description, generated from the code (3 endpoints so far) |
| `roleplay_result.schema.json` | the result format as a JSON schema, generated from our model |
| `ai-use-log/` | the log the BRD requires; the scaffold entry has two TODOs (account used, reviewer) |

---

## 9. What is real, what is a stub, what is not built
| Area | State |
|---|---|
| The 12 tables, the migration, the database helpers | **real**, tested |
| Schemas and the result format | **real**, tested, and checked against the real seed pack |
| `FakeLLM` and the LLM interface | **real** |
| Dev fake login, health and registration endpoints | **real** |
| Settings, seed loader, OpenAPI export | **real** |
| Job queue setup | **real**; the four jobs are **stubs** |
| Real LLM provider | **stub**; waiting for provider, models and keys |
| Proposal reading, OCR, brief | **not built** (`app/ingest/` is empty) |
| The conversation, persona prompts, escalation guard, turn limit | **not built** (`app/agent/` is empty) |
| Scoring, quote check, counting signals, blend, confidence | **not built** (`app/scoring/` is empty) |
| Reports | **not built** (`app/reports/` is empty) |
| Upload, session, scoring and admin endpoints | **not built** |
| Real login, deployment, the user interface, CI | **parked** |

No Postgres has been created yet (Docker is not installed on this machine). The tables have been built in SQLite files, and the migration compiles for Postgres in a test.

---

## 10. Assumptions and placeholders
Nothing below comes from the BRD or the program. All are easy to change.
1. **`handled` allowed values** (yes / partly / no): the seed pack only shows "partly".
2. **Escalation steps 1 to 4**: taken from the seed ladder. The seed's own 1 to 5 "pushback scale" contradicts its examples and is not used.
3. **Scoring:** three dimensions, weights 0.4 / 0.3 / 0.3, alpha 0.4, agreement gap 25, band cutoffs 90 / 75 / 50, pass cutoff 50.
4. **Persona knobs:** t_escalate 0.5, t_deescalate 0.7, min_turns 3, max_turns 8, grace_turns 0.
5. **Dev credentials:** local Postgres user, password and database are all `podc`; only for local work.
6. **A naming leftover:** `EndReason.concerns_resolved` now means "all checklist items covered". It may be renamed.
7. **Pod D's input differs from the program's result format.** Pod D takes a transcript, one number and short flag tags. We must agree the format, the score scale and the flag names with them and the TPM.
8. **Retention:** 30 days is configured but the nightly deletion job does not exist yet.

---

## 11. Review checklist
- [ ] Do the 12 tables and their columns cover what we need? Anything missing or unnecessary?
- [ ] Is "scenario required, proposal optional" on `session` the right call?
- [ ] Are the three scoring dimensions and weights acceptable as a starting point?
- [ ] Do we want our own `LLMClient` wrapper, or LangChain's chat model directly, as Pod 4 does?
- [ ] Should `EndReason.concerns_resolved` be renamed?
- [ ] Is it right that only the migration owner writes migrations?
- [ ] Which folders will each developer take? Update the README owner table.
- [ ] Are the TPM questions (in the README) complete?
- [ ] Has everyone read and understood every file they will rely on (BRD section 5.4)? Fill in the two TODOs in the AI-use log.
