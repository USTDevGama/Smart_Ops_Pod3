# Data model

The system remembers things in **5 tables** (PostgreSQL in real use, SQLite in tests). This page explains each table, each column and why it is there. The source of truth is `app/db/models.py`. Migrations are in `alembic/versions/`: `0001` created the first 12 tables and `0002` trimmed them to these 5.

**What was removed, and why.** Users, scoring, review, reports, the AI-call log and the audit log are not being built now, so their tables were dropped: `app_user`, `assessment`, `assessment_evidence`, `review`, `report`, `llm_call_log`, `audit_log`. They come back, through a new migration, when those features are built. The data shapes for scoring and the program's result format are still in `app/schemas/` for that work.

Plain-words key:
- **id**: every table has one. A unique row number (a UUID).
- **-> table**: this column points at a row in another table (a "foreign key"). The database refuses a value that does not exist there.
- **JSON**: a column holding a small structured document instead of a single value.
- **Never edited**: rows that are only ever added, so the record cannot be quietly changed.
- **`*_ref`**: a plain text name of the logged-in user (the `X-Dev-User` header for now). There is no user table; real login arrives later.

## How the tables connect
```mermaid
erDiagram
  config_version ||--o{ session : "persona and scenario versions"
  proposal ||--o{ proposal_segment : "split into chunks"
  proposal |o--o{ session : "optional"
  session ||--o{ turn : "chat messages"
```

## Settings

### `config_version` - every saved persona and scenario
One table holds both kinds, because they work the same way: the admin edits, and each edit saves a **new numbered version**. Published rows are never changed, so an old chat can always be explained by the exact settings it used.
| Column | Why it is there |
|---|---|
| `kind` | `persona` (the AI client) or `scenario` (the situation and the checklist of what a good answer contains). |
| `key` | A stable name for the thing, for example `verma-strict` or `vendor-delay`. |
| `version_no` | 1, 2, 3... for each edit of that key. Together `kind` + `key` + `version_no` must be unique. |
| `status` | `draft` (still being edited), `published` (usable), `retired` (replaced by a newer published version). |
| `config` | All the settings as JSON. The shape is checked by `PersonaConfig` or `ScenarioConfig` before saving. |
| `created_at` | When this version was saved. |

## The uploaded proposal

### `proposal` - an uploaded file and what we learned from it
| Column | Why it is there |
|---|---|
| `owner_ref` | Whose file it is (the login user). Access control: a trainee sees only their own. |
| `filename`, `file_type` | `filename` for display. `file_type` (`pdf`, `docx`, `txt`) picks the right reader. |
| `sha256` | A fingerprint of the file. Spots a duplicate upload so we reuse the earlier summary. |
| `blob_uri` | Where the original file is stored (a folder in development). The file is kept out of the database. |
| `status` | `queued`, `extracting`, `ready` or `failed`. The UI watches this. |
| `brief` | The structured summary of the proposal (claims, weak points, each citing chunk ids), as JSON. Empty until `ready`. |
| `error` | Why it failed, if it did. |
| `created_at` | Also starts the 30-day deletion clock. |

### `proposal_segment` - the proposal cut into numbered chunks
Each chunk can be pointed at, so the persona can cite one and code can check it exists.
| Column | Why it is there |
|---|---|
| `proposal_id` -> `proposal` | The proposal it belongs to. Deleted along with it. |
| `seq` | The chunk's order (unique within a proposal). |
| `page` | The page number (1 for plain text files). |
| `kind` | `text` (read directly) or `ocr` (read from an image of text). |
| `text` | The chunk itself. |
| `ocr_confidence` | How sure the OCR was (0 to 1). Empty for normal text. |

## The chat

### `session` - one roleplay run by one trainee
| Column | Why it is there |
|---|---|
| `trainee_ref` | Who is playing (the login user). |
| `proposal_id` -> `proposal` | The proposal being discussed. **Optional**: a session can run on the scenario alone. |
| `persona_version_id` -> `config_version` | The exact persona version used. |
| `scenario_version_id` -> `config_version` | The exact scenario version used. |
| `status` | `active` or `ended`. |
| `end_reason` | Why it ended: trainee ended it, turn limit, all checklist items covered, time limit, or admin. |
| `started_at`, `ended_at` | Timing. `ended_at` starts the 30-day deletion clock. |

### `turn` - the chat, one row per message. Never edited.
The full record of the conversation, and what any later score will be traced back to.
| Column | Why it is there |
|---|---|
| `session_id` -> `session` | Which session. |
| `idx` | Position in the chat: 0, 1, 2... unique per session. (The program's result format numbers messages from 1, so result turn = `idx` + 1.) |
| `role` | `persona` (the AI client, called "client" in the result format) or `trainee`. |
| `content` | The message text. |
| `escalation_level` | How tough the client was in that reply, step 1 to 4. Only on persona rows. Also gives the "current level" without extra state. |
| `refs` | The proposal chunks the client's question relied on. Only on persona rows. Code keeps only real chunk ids. |
| `evaluation` | The agent's judgement of a trainee answer: quality, which checklist items it met, whether it was evasive, a short quote. Only on trainee rows. Admins can see it; trainees cannot. |
| `idempotency_key` | A token the app sends with each message so a retry cannot create a duplicate. Trainee rows only. |
| `created_at` | Order and timing. |

## What we deliberately do not store
- Passwords, names or emails.
- API keys.
- A separate copy of the "current escalation level" or "open checklist items". They are worked out from the saved turns, so there is nothing to get out of sync.

## Deletion
A nightly job (not written yet) will delete data 30 days after a session ends, or 30 days after an upload that was never used. Deleting a session removes its turns. A proposal still used by a session is never deleted, and the API refuses to delete it.

## Looking at the tables on your machine
| Option | Needs Docker? | How |
|---|---|---|
| **Adminer** (browser) | yes | `docker compose up -d`, open http://localhost:8080. System: PostgreSQL, Server: `postgres`, User/Password/Database: `podc`. Run `uv run alembic upgrade head` first. |
| **DBeaver** or **pgAdmin** (desktop) | yes | Connect to `localhost:5432`, user `podc`, password `podc`, database `podc`. |
| **DB Browser for SQLite** or the VS Code "SQLite Viewer" extension | **no** | Set `PODC_DATABASE_URL=sqlite:///local.db`, run `uv run alembic upgrade head`, then open `local.db`. |
| **The diagram above** | no | Opens as a picture on GitHub and in the VS Code Markdown preview. |
