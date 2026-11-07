# Scoring and confidence formulas

This document records the current scoring contract and the proposed confidence
heuristic. Confidence parameters are starting values, not calibrated or approved
production thresholds.

## Overall score

Each criterion has:

- `points` in the range 0 to 1.
- A `weight` in the range 0 to 1.

Criterion weights must sum to 1. The overall score is:

```text
overall_score = 100 * sum(points_i * weight_i)
```

For four equally weighted criteria with points `0.5`, `0.7`, `0.4`, and `0.2`,
the score is `45.0 / 100`.

The points-to-status cutoffs below are proposed defaults and still need
confirmation:

| Status | Criterion points |
|---|---:|
| `not_met` | less than 0.30 |
| `partly` | 0.30 to less than 0.70 |
| `met` | 0.70 or greater |

These rules make the boundary values explicit: `0.30` is `partly`, and `0.70`
is `met`. The overall `handled` label is separate and needs its own agreed
mapping if it is derived from the overall score.

The sample report marks criterion C4 with `0.2` points as `partly`, which does
not match the proposed `0.30` lower cutoff. Until the rubric thresholds are
confirmed, the report sample fixes the output shape, while its example status
values and the default cutoffs remain illustrative.

The confidence values in that report are also illustrative rather than expected
outputs of this formula. With `llm_output.json`, the default rubric, and valid
questions/signals for all cited turns, the proposed formula yields criterion
confidence values `100`, `75`, `100`, and `100`, for a combined score of `93.75`
before rounding.

## Per-criterion confidence

Confidence is a review-priority heuristic from 0 to 100. It is not a
probability that a score is correct.

For criterion `i`:

```text
confidence_i = 100 * (0.40 * G_i + 0.35 * Q_i + 0.25 * M_i)
```

The weights are provisional.

| Term | Meaning | Proposed calculation |
|---|---|---|
| `G_i` | Evidence agrees with code-observed signals | Share of cited trainee turns where the criterion's signal agrees with the evidence polarity. |
| `Q_i` | Questions behind the evidence were valid | Share of cited exchanges whose client question passed the validity checks. |
| `M_i` | Criterion status is away from a cutoff | `min(1, d / 0.10)`, where `d` is the distance from the points to the nearest status cutoff. |

Question validity checks are: grounded in the scenario or cited proposal segments,
in persona, and consistent with the escalation rules. A proposal reference must
exist; its existence alone does not establish relevance.

### Evidence and missing-signal rules

- If points are above zero but there are no valid cited trainee turns, criterion
  confidence is zero.
- If points are zero and there are no citations, `G_i` is one only when no
  matching signal fired on any trainee turn. `Q_i` is the average validity of
  the session's client questions.
- If a criterion has no matching code signal, omit `G_i` and renormalize the
  remaining confidence weights: `confidence_i = 100 * (0.35 * Q_i + 0.25 * M_i) / 0.60`.
- Evidence citations must identify trainee answers. The report's logical turn
  is an exchange: one client question and its trainee reply share the same turn
  number. Database message rows remain distinct and must be mapped to that
  exchange number.

The `0.10` margin is also provisional. With the proposed cutoffs, confidence
margin is zero exactly at `0.30` or `0.70`, and reaches one at least `0.10` away
from the nearest cutoff.

## Session confidence

Let `w_i` be the criterion weights and `N_invalid` the number of invalid client
questions:

```text
base_confidence = sum(w_i * confidence_i)
session_confidence = clamp(base_confidence - 10 * N_invalid, 0, 100)
```

For sessions with fewer than three trainee exchanges, cap the result at 60:

```text
session_confidence = min(session_confidence, 60)
```

The deduction, short-session cap, and confidence bands are provisional:

| Band | Session confidence |
|---|---:|
| `high` | 75 or greater |
| `medium` | 50 to less than 75 |
| `low` | less than 50 |

The validity deduction applies at the session level because an invalid client
question can affect the whole conversation, including turns not cited by a
criterion.

## Decisions and items to confirm

- **Scoring formula:** weighted criterion points, multiplied by 100.
- **Point range and weights:** points are 0 to 1; criterion weights sum to 1.
- **Turn meaning for this report:** a client question and its trainee reply are
  one logical turn and share a turn number.
- **Still provisional:** status cutoffs, confidence component weights, the
  `0.10` margin, the 10-point invalid-question deduction, the short-session
  cap, and confidence bands. In particular, reconcile the C4 status in the
  report sample with the proposed `0.30` lower cutoff.
- **Needs scenario-specific definitions and testing:** code signals per
  criterion, polarity semantics, and question-validity checks.

Tune the provisional values against representative seed cases and human
assessments before treating confidence bands as operational thresholds.
