"""Turns the service's `SessionContext` into what the prompts need. No prompt text lives here.

- `doc_text` reads the demand and the profile, whatever shape ingestion gave them.
- `redact` takes contact details and ID-like numbers out of the resume before it reaches a model.
- `settled_scenario` / `met_items` keep the conversation in one scenario, from what is stored.
- `legal_levels` is the range of levels the service will keep as they are.
"""

import re

from app.agent.engine import SessionContext
from app.schemas import ScenarioConfig
from app.schemas.enums import TurnRole

MAX_DOC_CHARS = 24_000

_PAGE_MARK = re.compile(r"<!--\s*page\s+(\d+)\s*-->", re.IGNORECASE)
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_BLANK_RUNS = re.compile(r"\n{3,}")


# --- documents ----------------------------------------------------------------------------------


def doc_text(content: object) -> str:
    """The prose of an extracted document, or "" if there is none.

    Ingestion currently gives `{"text": "<markdown>"}` and owns that shape, so this accepts any
    JSON: a bare string, a "text" or "markdown" key, or nested sections and pages. Page markers
    become "[page N]", other HTML comments are dropped, and a very long document is cut.
    """
    text = _flatten(content)
    text = _PAGE_MARK.sub(r"[page \1]", text)
    text = _COMMENT.sub("", text)
    text = _BLANK_RUNS.sub("\n\n", text).strip()
    if len(text) > MAX_DOC_CHARS:
        text = text[:MAX_DOC_CHARS].rstrip() + "\n[the document continues but was cut here]"
    return text


def _flatten(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("text", "markdown"):
            if isinstance(value.get(key), str):
                return value[key]
        return _join(value.values())
    if isinstance(value, list | tuple):
        return _join(value)
    return ""  # None, numbers and booleans carry no prose


def _join(parts) -> str:
    return "\n\n".join(p for p in (_flatten(part) for part in parts) if p)


# --- privacy (BRD BR-13) ------------------------------------------------------------------------

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_LINK = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_LONG_NUMBER = re.compile(r"\+?\d[\d \t().-]{6,}\d")  # phone numbers, grouped ID numbers
_PAN_LIKE = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")
_PASSPORT_LIKE = re.compile(r"\b[A-Z]\d{7}\b")


def _mask_number(match: re.Match) -> str:
    groups = re.findall(r"\d+", match.group(0))
    if sum(len(g) for g in groups) < 9:
        return match.group(0)  # a date range or a figure, not a phone or ID number
    if all(len(g) == 4 and 1900 <= int(g) <= 2100 for g in groups):
        return match.group(0)  # a run of years
    return "[number]"


def redact(text: str) -> str:
    """Best effort: remove emails, links, phone and ID-like numbers from a resume.

    Names and addresses are not removed (that needs more than patterns), so this reduces what
    leaves the platform but is not a guarantee. It is applied to the profile only: the trainee's
    own answers are never altered, because evidence quotes must match them exactly.
    """
    text = _EMAIL.sub("[email]", text)
    text = _LINK.sub("[link]", text)
    text = _PAN_LIKE.sub("[id]", text)
    text = _PASSPORT_LIKE.sub("[id]", text)
    return _LONG_NUMBER.sub(_mask_number, text)


# --- which scenario, which checklist items --------------------------------------------------------


def find_scenario(scenarios: list[ScenarioConfig], scenario_id: str) -> ScenarioConfig | None:
    key = scenario_id.strip().casefold()
    return next((s for s in scenarios if s.id.strip().casefold() == key), None)


def met_items(ctx: SessionContext) -> set[str]:
    """Checklist items earlier answers were already credited with (as saved by the service)."""
    return {
        item
        for turn in ctx.turns
        if turn.role == TurnRole.TRAINEE and turn.evaluation
        for item in turn.evaluation.checklist_met
    }


def settled_scenario(ctx: SessionContext) -> ScenarioConfig | None:
    """The scenario this conversation is already in, if the stored evidence shows it.

    The service does not save which scenario the opening chose, but it does save which checklist
    items each answer met, and those are word for word items of one scenario. Whichever scenario
    owns most of them (with no tie) is the one. Before any item is met this returns None and the
    model works it out from the conversation.

    If the service later saves the chosen scenario, read it here first; nothing else changes.
    """
    met = met_items(ctx)
    if not met:
        return None
    counts = [(len(met & set(s.good_answer_contains)), s) for s in ctx.scenarios]
    best = max((count for count, _ in counts), default=0)
    owners = [s for count, s in counts if count == best and best > 0]
    return owners[0] if len(owners) == 1 else None


# --- levels and history -------------------------------------------------------------------------


def legal_levels(ctx: SessionContext) -> tuple[int, int]:
    """The levels the client may speak at next: one step either way, inside the ladder.

    The service clamps the proposed level to exactly this range. The reply is written at the level
    it proposes, so asking for more than the range would save a tone that does not match.
    """
    top = ctx.persona.max_step
    level = max(1, min(ctx.level, top))
    return max(1, level - 1), min(top, level + 1)


def history_lines(ctx: SessionContext) -> list[str]:
    """One line per earlier answer: how it was judged, and how the client then spoke.

    Built from the service's saved evaluations (our own output), never from trainee text.
    """
    lines: list[str] = []
    for i, turn in enumerate(ctx.turns):
        if turn.role != TurnRole.TRAINEE:
            continue
        ev = turn.evaluation
        if ev is None:
            judged = "not judged"
        else:
            judged = (
                f"quality {ev.answer_quality:.2f}, {'evasive' if ev.evasive else 'not evasive'}, "
                f"composure {ev.composure:.2f}"
            )
        after = ctx.turns[i + 1] if i + 1 < len(ctx.turns) else None
        spoke = ""
        if after is not None and after.role == TurnRole.PERSONA and after.escalation_level:
            spoke = f"; you then spoke at level {after.escalation_level}"
        lines.append(f"Answer {len(lines) + 1}: {judged}{spoke}")
    return lines
