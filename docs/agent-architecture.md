# The agent: how one client reply is produced

Owner: Shubra. Code: `app/agent/`. This page explains the design so a teammate can review it and so the agent can be changed safely.

## Where it sits
```
 UI --> chat service (app/sessions, Jayant)  --calls-->  TurnEngine (app/agent, this page)
          saves turns, enforces the turn limit,                 |
          clamps the level, ends the session                    '--> LLMClient (app/llm) --> model
```
The chat service and the agent meet at one small interface, `TurnEngine` in `app/agent/engine.py`:

| Call | The service gives | The agent returns (`TurnOutput`) |
|---|---|---|
| `opening(ctx)` | persona, scenario, brief (optional) | the client's first line |
| `respond(ctx, answer)` | the same, plus the chat so far, the current level, the open checklist items and the trainee's answer | a judgement of the answer (`Evaluation`), the client's reply, and the proposal chunks the reply relied on (`refs`) |

The service saves the trainee's turn together with the `Evaluation`, then the client's turn. **Scoring reads those saved rows**, so what the agent returns is also a contract with Disha (scoring): `checklist_met`, `answer_quality`, `composure`, `quote`, and the level on each client turn.

## The principle
**The model judges and speaks. Plain code makes every rule decision.** That keeps the agent testable, repeatable, and hard to manipulate.

| The model does | Code does |
|---|---|
| rates the answer (0 to 1), says which checklist items it met, flags evasiveness | decides the client's level (`escalation.py`) |
| picks a short quote from the answer | checks the quote really is in the answer (`grounding.py`) |
| writes the client's reply | tidies it, checks citations are real, rewrites it if its tone does not match the level |
| | (the chat service) enforces one step at a time, the turn limit, ending the session |

## One turn, step by step
```
 respond(ctx, answer)
   1 prompts.py      build the prompt: trusted rules -> `system`; trainee/proposal text -> `user`, as data
   2 model call      ONE call returns TurnDraft: judgement + quote + reply + cites
   3 grounding.py    quote in the answer? (else ONE repair call, else AgentError)
                     checklist numbers -> real item texts; brief labels (B1) -> real chunk ids
   4 escalation.py   next level from the judgement (code only)
   5 rewrite?        if the reply was written at a different level than step 4 chose: ONE extra call
   6 return          TurnOutput (the service saves it)
```
A normal turn is one model call (about 11 per 8-turn session, as planned). A second call happens only for a quote repair or a tone rewrite. Any failure raises `AgentError`; the service answers 502 and **saves nothing**, so the trainee keeps their turn.

## The escalation rules (`escalation.py`)
Knobs live on the persona (`PersonaConfig`): `t_escalate` (0.5), `t_deescalate` (0.7), the ladder.

| Answer | Level change |
|---|---|
| evasive, or quality below `t_escalate` | one step tougher (capped at the ladder's top) |
| not evasive and quality at or above `t_deescalate`, **and the previous answer was too** | one step easier (never below 1) |
| anything else, including one good answer after a weak one | stay |

The chat service then clamps the result to at most one step from the previous level, as a second safety net.

## Safety (BRD traps C3 and C6, BR-13)
- Trusted text (what an admin wrote, plus our fixed rules) is the only thing in the `system` prompt. **Nothing a trainee wrote, and nothing from a proposal, is ever in it.**
- The trainee's answer, the chat so far and the proposal brief go in the `user` message, each inside a tag and described as material, not instructions. Our own tags are stripped from that text first, so it cannot close a wrapper and start "talking".
- Only the trainee's own answers are judged. The prompt tells the model that repeating a word like "budget" does not make an answer good.
- Prompts and errors never contain names (the service passes none) and `AgentError` messages never contain trainee text.

## Grounding (BRD BR-12)
Everything the model points at is checked against the real thing:
- **quote**: matched (ignoring case and spacing) inside the trainee's answer and returned as the exact words from it, so a later word-for-word check passes. Not found twice means the turn fails.
- **checklist**: the model answers with numbers from the open-items list; code turns them into the real item texts. Invented or already-met numbers are ignored.
- **cites**: the model answers with brief labels (`B1`...); code maps them to real chunk ids. Unknown labels are dropped. (The service also drops any chunk that is not in this session's proposal.)

## Files
| File | Job |
|---|---|
| `engine.py` | the `TurnEngine` interface (Jayant) and `get_engine()`, the one switch |
| `llm_engine.py` | `LLMTurnEngine`: the real engine described above |
| `prompts.py` | all prompt text, `PROMPT_VERSION` |
| `drafts.py` | what the model is asked to return (looser than `TurnOutput`) |
| `grounding.py` | quote, checklist and citation checks, tag neutralising |
| `escalation.py` | the level rules |
| `errors.py` | `AgentError` |
| `placeholder.py` | the no-LLM stand-in (Jayant), used while `PODC_LLM_PROVIDER=fake` |

## Decisions and open points
- **Plain steps, not LangGraph.** The flow is linear with one branch, so it is plain, separately tested functions. It can be wrapped in a LangGraph graph later without changing the interface. The chat service does not import any agent framework (a test enforces this).
- **No streaming yet.** The service sends the whole reply as one `message` event, so the model call is not streamed.
- **The real model is not connected.** `get_engine()` uses the placeholder while `PODC_LLM_PROVIDER=fake`; any other value uses `LLMTurnEngine`, which needs Jayant's `ProviderLLM` (not written; it raises "not implemented" until the keys arrive). Until then everything is tested with a scripted `FakeLLM`. **Prompt wording and how well a real model follows it are untested.**
- **Known-answer cases from the program's seed pack** (strong, vague, evasive, keyword-stuffed, override) can only really be checked against a real model. The seed pack is confidential and this repo is public, so those cases must be run from a local copy, never committed.
- **The opening is written by the model**; the service stores it at level 1.
- **Temperature 0.2.** Low, for a stable judgement; a little above 0 so the client's wording is not robotic.
