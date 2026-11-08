"""The character card as a plain dict, built from simple form values. No Streamlit in here."""

import json
from pathlib import Path

SAMPLE = Path(__file__).resolve().parent.parent / "samples" / "personas" / "ms_verma_strict.json"

# Used only if the sample file is not there (the API still validates whatever is sent).
FALLBACK = {
    "name": "Ms. Verma",
    "role": "Finance head at a fictional logistics company",
    "style": "Crisp and formal, short sentences, no patience for waffle",
    "main_concerns": ["Budget: no spend beyond the approved limit", "Dates: one firm date"],
    "rules": ["Stay in character for the whole conversation", "Push back on vague answers"],
    "escalation_ladder": [
        {"step": 1, "move": "Ask a short clarifying question"},
        {"step": 2, "move": "Point out what the vague answer leaves unanswered"},
        {"step": 3, "move": "Demand a firm date and a cost"},
        {"step": 4, "move": "Say plainly that she is losing confidence"},
    ],
    "t_escalate": 0.5,
    "t_deescalate": 0.7,
    "min_turns": 3,
    "max_turns": 8,
    "grace_turns": 0,
}


def default_persona() -> dict:
    try:
        return json.loads(SAMPLE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return dict(FALLBACK)


def default_scenarios_json() -> str:
    path = SAMPLE.parent.parent / "scenarios" / "vendor_delay.json"
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return '{"scenarios": []}'


def split_lines(text: str) -> list[str]:
    """One item per non-empty line."""
    return [line.strip() for line in text.splitlines() if line.strip()]


def ladder_rows(rows: list[dict]) -> list[dict]:
    """The ladder as the API wants it: whole steps with a move, empty rows dropped."""
    steps = []
    for row in rows:
        move = str(row.get("move") or "").strip()
        step = row.get("step")
        if move and step is not None and step == step:  # a blank number arrives as NaN
            steps.append({"step": int(step), "move": move})
    return steps


def persona_config(
    *,
    name: str,
    role: str,
    style: str,
    main_concerns: str,
    rules: str,
    ladder: list[dict],
    t_escalate: float,
    t_deescalate: float,
    min_turns: int,
    max_turns: int,
    grace_turns: int,
    version: str | None = None,
) -> dict:
    """The dict the API validates. Anything wrong comes back as a clear error, not a crash."""
    config = {
        "name": name.strip(),
        "role": role.strip(),
        "style": style.strip(),
        "main_concerns": split_lines(main_concerns),
        "rules": split_lines(rules),
        "escalation_ladder": ladder_rows(ladder),
        "t_escalate": t_escalate,
        "t_deescalate": t_deescalate,
        "min_turns": int(min_turns),
        "max_turns": int(max_turns),
        "grace_turns": int(grace_turns),
    }
    if version:
        config["version"] = version
    return config
