# Scoring and report work: session context

Snapshot as of 2026-11-06. This note records the intended flow, the assumptions introduced
during implementation, the current code state, and what was found in the agent branch. It
contains no confidential seed-pack, trainee, or client data.

## Intended project flow

The main-branch flow changed from configurable personas and scenarios with proposal segments to:

- The admin configures personas and uploads one shared project demand document.
- The trainee uploads a profile/resume when starting a session.
- The scenario set is imported as a catalog; the conversation agent selects a scenario using
  the session context. Persona is the configurable choice for a session.
- The demand and profile are short extracted JSON documents. There are no document segments.
- The conversation agent conducts the chat and supplies the expected final criterion-scoring
  output in the shape represented by `samples/results/llm_output.json`.
- This branch's post-conversation work validates that output, calculates score and confidence,
  and builds the final report. Azure storage is deferred.

The final Markdown report must follow `samples/results/PodC_Sample_Report_v4.md`, then be
convertible to HTML and PDF. No dedicated assessment/report tables are to be restored without
an explicit later decision.

## Scoring and confidence decisions

- Criterion points are in `[0, 1]`; criterion weights sum to `1`.
- Overall score is `100 * sum(points_i * weight_i)`.
- Status is derived in code from criterion points and the configured cutoffs.
- Per-criterion confidence is a review heuristic using evidence/signal agreement (`G`), question
  validity (`Q`), and distance from a status cutoff (`M`):
  `100 * (0.40 * G + 0.35 * Q + 0.25 * M)`.
- Session confidence is the weighted mean of criterion confidence, less 10 points per invalid
  client question, clamped to `[0, 100]`. It is capped at 60 when there are fewer than three
  trainee exchanges.
- The weights, cutoffs, margin, penalty, cap, and confidence bands are provisional, not
  calibrated production values.
- Report/scoring exchange numbering is one client question plus its trainee reply. The outgoing
  Pod D result contains goal scores and no transcript turn numbers.

## What the scoring/report commit added

Commit `1cf9a09` (`added scoring code`) added a consumer-side pipeline:

- `ScoringOutput` in `app/schemas/assessment.py` describes criterion IDs, points, reasons,
  evidence turn/polarity, strengths, gaps, and unanswered objections. It matches the shape of
  `samples/results/llm_output.json`.
- `app/scoring/processor.py` accepts that output, a scoring configuration, and validation
  context; it checks criteria/evidence, derives statuses and confidence, and computes the
  weighted score.
- `app/reports/generator.py` builds report Markdown, sanitized HTML, and PDF from a completed
  session and a validated assessment.
- Scoring configuration, formula documentation, tests, and generated schemas were added or
  updated.

The sample `llm_output.json` was already present in the workspace before those scoring changes.
Its `points` values were later changed from JSON strings to JSON numbers to match the numeric
`ScoringOutput.points` field.

The commit did **not** add code that asks the conversation agent for `ScoringOutput`, nor does
it calculate criterion points from per-turn `Evaluation` rows. The scorer task is still a stub.
The processor assumes it is handed criterion-level output.

`docs/roleplay_result.schema.json` is a different contract: the outgoing Pod D `roleplay-result`.
It is not the conversation-agent turn output and not the criterion-scoring JSON. A separate
`docs/scoring_output.schema.json` now documents the scoring JSON shape.

## Where implementation discussions went wrong

The original request said the post-conversation work starts after the LLM provides the format in
`samples/results/llm_output.json`. It did not ask for a separate scoring LLM call.

I incorrectly interpreted that file as the response of a separate post-session scoring LLM. I
then described `ScoringOutput` as a “scoring LLM response” and talked about a separate scorer as
if that had been agreed. That was my assumption, not a user decision.

The per-turn `TurnOutput` interface already existed in the shared repository contract. I did not
add it in the scoring commit. I also repeatedly conflated that existing per-turn response with
the final criterion-level output, which obscured the intended handoff.

The corrected intended ownership is:

1. The conversation-agent component supplies the final criterion-level output in the
   `llm_output.json` shape.
2. This branch validates that output, uses the saved session data as needed, calculates the
   agreed math/confidence, and generates the report.
3. Do not introduce a separate scoring LLM unless the user explicitly changes this decision.

The current agent branch does not yet expose the final criterion-level output, so the intended
handoff is not implemented end to end.

## What the current conversation-agent interface says

The existing `TurnEngine` contract in `app/agent/engine.py` has `opening(ctx)` and
`respond(ctx, answer)`, each returning `TurnOutput`. `Evaluation` in
`app/schemas/conversation.py` is per trainee reply and contains:

- `answer_quality` in `[0, 1]`
- `checklist_met`
- `evasive`
- `composure` in `[0, 1]`
- a quote from the trainee's answer
- `proposed_level`

The service saves this evaluation on the trainee turn, and saves the persona reply and clamped
escalation level on the persona turn. This is not a criterion-points payload.

## Agent branch findings

The latest published ref inspected was
`origin/feature/podc-agent-turn-engine` at `6470233` (`Document the agent for the team and log
the AI use`). It is not merged into `d/score-report`. It is based on the updated main flow and
no longer uses proposal-segment citations. That branch also includes Kedar's PDF/DOCX/TXT
ingestion work and related tests; the details below concern the agent portion.

The agent implementation asks the model for:

- Opening draft: `scenario_id` and the opening `reply`.
- Turn draft: `scenario_id`, internal `addressed`/`avoided` notes, `answer_quality`, `evasive`,
  `composure`, checklist item numbers, a trainee-answer `quote`, `proposed_level`, and the
  client's next `reply`.

The engine checks that the scenario exists, snaps the quote to text actually in the trainee's
answer, maps checklist positions to real scenario checklist text, bounds quality/composure and
checks the proposed level/reply. It allows one retry for malformed output. It then returns the
shared per-turn `TurnOutput`; `addressed` and `avoided` are not saved.

That branch's current agent code does **not** provide the final criterion-level
`ScoringOutput`/`llm_output.json` payload, does not provide criterion IDs/points/reasons, and
does not cite profile/demand/scenario source paths to explain each client question. The quote is
evidence from the trainee's reply, not provenance for the client's question.

The branch's opening draft includes a `scenario_id`, but the engine drops it before the service
saves the turn. The agent documentation calls recovering the selected scenario from transcript
and checklist data a stopgap and proposes passing/persisting the selected scenario through the
existing nullable `session.scenario_version_id`. Until that is done, report generation cannot
reliably identify the chosen scenario.

## Current implementation gaps

- No implemented handoff from the conversation-agent component to the final `ScoringOutput`.
- `run_assessment` and `render_report` in `app/workers/tasks.py` are stubs; the session-end hook
  in `app/sessions/hooks.py` is a no-op. The discussed single Celery post-session task is not
  implemented.
- `build_assessment` requires a `ScoringValidationContext` covering all client exchanges,
  including `question_validity` and trainee signals. There is no adapter that builds this from
  saved turn rows, and the current agent output has no question-validity result or source
  provenance.
- The scenario-specific sample rubric is vendor-delay-oriented; a rubric strategy for the full
  imported scenario catalog remains to be confirmed.
- `session.scenario_version_id` is not set by the current main session flow, while the report
  generator requires a scenario configuration.
- Assessment/report artifacts are not persisted or uploaded to Azure. The report generator
  returns artifacts in memory.
- The external `RoleplayResult` contract and the internal criterion-scoring format are distinct.
  `build_pod_d_result` maps C1+C3 to G06, C2 to G08, and C4 to G10 using criterion weights,
  then scales and rounds points to integer scores 1-5 (zero clamps to 1 for Pod D's current
  constraint). Pod C's `trainee` table is keyed by `trainee_id`; profiles and sessions reference
  that ID while keeping the entered display name for review. The post-session job upserts scores
  to Pod D whenever `TRAINEE_DB_URL` is configured, including dev-auth runs; those entered IDs
  are not verified.

## Repository status at this snapshot

- Current branch: `d/score-report`.
- `HEAD` is `0769ecf` (`pull from main`), a merge commit with parents `1cf9a09` and `c01fd6d`.
  The merge is complete; there are no unresolved conflict paths. The working tree was clean
  when checked. The local branch was six commits ahead of `origin/d/score-report`.
- `origin/main` was at `c01fd6d`.
- The latest inspected agent branch ref was `6470233` and remained a separate branch.
- After resolving the merge, validation passed: 139 tests passed, 5 skipped, and
  `uv run ruff check .` passed.

## Next alignment step

Before wiring the post-session task, agree with the agent owner on how the conversation-agent
component delivers its final criterion-level output and selected scenario. Then connect that
output to `ScoringOutput`/`build_assessment`, build or receive the required validation context,
and generate the report. Keep this as one conversation-agent component; do not add a separate
scoring LLM on the basis of my earlier assumption.
