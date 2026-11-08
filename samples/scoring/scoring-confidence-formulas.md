# Scoring and confidence formulas

The score and the confidence are two separate numbers. The score says how well the trainee did.
The confidence says how much a human should double-check that score. Confidence never changes the
score. Confidence parameters are starting values, not calibrated or approved production
thresholds.

## The rubric (fixed, rubric version `r2`)

Four criteria apply to every scenario. They are defined in `app/scoring/rubric.py` and mirrored in
`samples/scoring/default.json` (a test keeps the two equal). The scoring model sees each
criterion's id, label and description. It never sees weights, cutoffs or signal keys.

| ID | Criterion | Weight |
|---|---|---:|
| C1 | Answers directly and specifically | 25% |
| C2 | Holds up under pressure | 30% |
| C3 | Credible and consistent | 25% |
| C4 | Takes ownership and offers a next step | 20% |

## Overall score

Each criterion has `points` from the scoring model (0 to 1) and a `weight`. Weights sum to 1.

```text
overall_score = 100 * sum(points_i * weight_i)
```

Sample (`results/llm_output.json`, points 0.5 / 0.7 / 0.4 / 0.2):
`100 * (0.5*0.25 + 0.7*0.30 + 0.4*0.25 + 0.2*0.20) = 47.5`.

## Status and `handled`

| Status | Criterion points |
|---|---:|
| `not_met` | less than 0.30 |
| `partly` | 0.30 to less than 0.70 |
| `met` | 0.70 or greater |

`handled` is derived from the overall score (as 0 to 1) with `handled_cutoffs`:
`yes` at 0.70 or more, `partly` at 0.40 or more, otherwise `no`. The sample's 47.5 is `partly`.

## Per-criterion confidence

A review-priority heuristic from 0 to 100. It is not a probability that a score is correct.

```text
confidence_i = 100 * (0.40 * G_i + 0.20 * Q_i + 0.40 * M_i)
```

| Term | Meaning | Calculation |
|---|---|---|
| `G_i` | The model's evidence agrees with the code markers | Share of cited trainee exchanges where the criterion's marker agrees with the evidence polarity (marker present for `positive`, absent for `negative`). |
| `Q_i` | The client questions behind the evidence were valid | Share of cited exchanges whose client message passed the validity rules. |
| `M_i` | The status is away from a cutoff | `min(1, d / 0.10)`, where `d` is the distance from the points to the nearest status cutoff. |

If points are above zero but nothing is cited, confidence is zero. If a criterion has no marker,
`G_i` is dropped and the other weights are renormalised (`(0.20*Q + 0.40*M) / 0.60`). That
happens for C3's `grounded` marker when the session has no resume and no demand document, because
nothing could be compared.

### Code markers (`app/scoring/signals.py`)

Set per trainee answer from its text, the evaluation the agent saved for it (`answer_quality`,
`evasive`, `composure`) and the resume and demand text. Cheap text rules: a missed marker lowers
confidence, it does not say the answer was bad.

| Marker | Criterion | Set when |
|---|---|---|
| `has_specifics` | C1 | a figure or date, not evasive, answer quality at least 0.5 |
| `kept_composure` | C2 | composure at least 0.6 and no over-promising words |
| `grounded` | C3 | no experience claim with a figure found in neither the documents nor the client's message, and the answer shares words with the documents or admits a limit |
| `has_commitment` | C4 | a first-person commitment or ownership phrase, not evasive |

### Question validity (`app/scoring/validity.py`)

A client message is valid when it has a saved escalation level inside the persona's ladder, the
level moved by at most one step, it is not a near-copy of an earlier client message, and it
shares a meaningful word with the persona's concerns, the demand or the resume. These are shallow
rules, which is why `Q_i` has the smallest weight.

## Session confidence

```text
base_confidence = sum(w_i * confidence_i)
session_confidence = clamp(base_confidence - 5 * N_invalid, 0, 100)
```

For sessions with fewer than three trainee exchanges, the result is capped at 60.

| Band | Session confidence |
|---|---:|
| `high` | 75 or greater |
| `medium` | 50 to less than 75 |
| `low` | less than 50 |

Sample (all questions valid, markers only on turns 3 and 4): criterion confidences 100 / 40 / 100
/ 100, session confidence 82. C2 is low because its model evidence cites turn 3 as positive while
no composure marker fired there, and because 0.7 sits exactly on the `met` cutoff.

## Still provisional

Status cutoffs, `handled` cutoffs, confidence weights, the 0.10 margin, the 5-point deduction,
the short-session cap and the bands are untuned guesses. Tune them against representative seed
cases and human assessments before treating the bands as operational thresholds. Marker and
validity rules need the same check.
