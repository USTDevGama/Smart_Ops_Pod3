"""Build Markdown, HTML, and PDF reports from a completed session and validated scores."""

import os
import re
from dataclasses import dataclass
from datetime import datetime
from html import escape
from pathlib import Path
from uuid import UUID

import bleach
from fpdf import FPDF
from markdown import markdown
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models as m
from app.reports.schemas import ReportNote, ValidatedAssessment
from app.schemas.config import PersonaConfig
from app.schemas.enums import SessionStatus, TurnRole


class ReportSessionNotFoundError(LookupError):
    """The requested session does not exist."""


class ReportNotReadyError(ValueError):
    """The session is not complete enough to create a final report."""


class ReportDataError(ValueError):
    """The stored session data cannot safely support the report."""


@dataclass(frozen=True)
class TranscriptExchange:
    turn: int
    client_text: str | None
    trainee_text: str | None
    escalation_level: int | None


@dataclass(frozen=True)
class ReportData:
    session_id: str
    trainee_name: str
    trainee_id: str | None
    persona_version: str
    ended_at: datetime
    end_reason: str
    escalation_peak: int | None
    transcript: tuple[TranscriptExchange, ...]
    assessment: ValidatedAssessment


@dataclass(frozen=True)
class ReportArtifacts:
    markdown: str
    html: str
    pdf: bytes


_HTML_TAGS = {
    "a",
    "blockquote",
    "br",
    "code",
    "em",
    "h1",
    "h2",
    "h3",
    "h4",
    "hr",
    "li",
    "ol",
    "p",
    "pre",
    "strong",
    "table",
    "tbody",
    "td",
    "th",
    "thead",
    "tr",
    "ul",
}

_HTML_ATTRIBUTES = {
    "a": ["href", "title"],
    "td": ["align", "width"],
    "th": ["align", "width"],
}
_HTML_PROTOCOLS = {"https", "http", "mailto"}

_END_REASON_LABELS = {
    "admin_ended": "admin ended",
    "concerns_resolved": "objections exhausted",
    "time_limit": "time limit",
    "trainee_ended": "trainee ended",
    "turn_cap": "turn limit reached",
}

_STATUS_LABELS = {
    "not_met": "not met",
    "partly": "partly",
    "met": "met",
}


def load_report_data(
    db: Session, session_id: UUID, assessment: ValidatedAssessment
) -> ReportData:
    """Read pinned settings and transcript rows, then validate report citations."""
    session = db.get(m.RoleplaySession, session_id)
    if session is None:
        raise ReportSessionNotFoundError(f"session {session_id} was not found")
    if session.status != SessionStatus.ENDED or session.ended_at is None:
        raise ReportNotReadyError("a final report requires an ended session")

    persona_version = db.get(m.ConfigVersion, session.persona_version_id)
    if persona_version is None:
        raise ReportDataError("the session's pinned persona version is missing")

    persona = PersonaConfig.model_validate(persona_version.config)
    rows = list(
        db.scalars(
            select(m.Turn).where(m.Turn.session_id == session.id).order_by(m.Turn.idx)
        )
    )
    if not rows:
        raise ReportDataError("the ended session has no transcript")

    exchanges: list[TranscriptExchange] = []
    expected_role = TurnRole.PERSONA
    expected_idx = 0
    client_text: str | None = None
    trainee_text: str | None = None
    escalation_level: int | None = None

    for row in rows:
        if row.idx != expected_idx or row.role != expected_role:
            raise ReportDataError(
                "transcript messages are not in the expected client/trainee order"
            )

        if row.role == TurnRole.PERSONA:
            client_text = row.content
            trainee_text = None
            escalation_level = row.escalation_level
        else:
            trainee_text = row.content

        if row.role == TurnRole.TRAINEE or row is rows[-1]:
            exchanges.append(
                TranscriptExchange(
                    turn=(row.idx // 2) + 1,
                    client_text=client_text,
                    trainee_text=trainee_text,
                    escalation_level=escalation_level,
                )
            )

        expected_idx += 1
        expected_role = (
            TurnRole.TRAINEE if expected_role == TurnRole.PERSONA else TurnRole.PERSONA
        )

    trainee_exchange_numbers = {
        exchange.turn for exchange in exchanges if exchange.trainee_text is not None
    }
    _validate_citations(assessment, trainee_exchange_numbers)

    levels = [exchange.escalation_level for exchange in exchanges if exchange.escalation_level]
    end_reason = session.end_reason.value if session.end_reason else "unknown"
    return ReportData(
        session_id=str(session.id),
        trainee_name=session.trainee_ref,
        trainee_id=session.trainee_id,
        persona_version=persona.version or f"{persona_version.key} v{persona_version.version_no}",
        ended_at=session.ended_at,
        end_reason=_END_REASON_LABELS.get(end_reason, end_reason.replace("_", " ")),
        escalation_peak=max(levels) if levels else None,
        transcript=tuple(exchanges),
        assessment=assessment,
    )


def _validate_citations(
    assessment: ValidatedAssessment, trainee_exchange_numbers: set[int]
) -> None:
    citations = [
        evidence.turn
        for criterion in assessment.criteria
        for evidence in criterion.evidence
    ]
    citations.extend(
        turn
        for note in [*assessment.strengths, *assessment.gaps]
        for turn in note.evidence_turns
    )
    missing = sorted(set(citations) - trainee_exchange_numbers)
    if missing:
        raise ReportDataError(
            f"evidence cites missing trainee exchanges: {', '.join(map(str, missing))}"
        )


def render_markdown(data: ReportData) -> str:
    """Render the canonical report Markdown with one logical turn per exchange."""
    assessment = data.assessment
    escalation_peak = (
        str(data.escalation_peak) if data.escalation_peak is not None else "Not recorded"
    )
    review_label = "required" if assessment.human_review_required else "not required"
    lines = [
        "# Stakeholder Roleplay Assessment",
        "",
        (
            f"Session: {_md_text(data.session_id)} | "
            f"Trainee name: {_md_text(data.trainee_name)} | "
            f"Trainee ID: {_md_text(data.trainee_id or 'Not recorded')} | "
            f"Persona: {_md_text(data.persona_version)} | "
            f"Ended: {_md_text(data.end_reason)} | "
            f"Date: {data.ended_at.strftime('%d %b %Y')}"
        ),
        "",
        "## Result",
        "",
        f"- Overall score: **{assessment.overall_score:.1f} / 100**",
        f"- Handled: **{assessment.handled}**",
        f"- Escalation peak: **{escalation_peak}** of 4",
        f"- Admin review: **{review_label}**",
        f"- Confidence score: {assessment.confidence_score:.0f}",
        "",
        "## Score breakdown",
        "",
        "| ID | Criterion | Weight | Status | Points | Confidence | Evidence |",
        "|---|---|---:|---|---:|---:|---|",
    ]

    for criterion in assessment.criteria:
        evidence = ", ".join(
            f"Turn {item.turn} ({'+' if item.polarity == 'positive' else '-'})"
            for item in criterion.evidence
        ) or "None"
        if criterion.reason:
            evidence = (
                f"{evidence}: {_table_text(criterion.reason)}"
                if evidence != "None"
                else _table_text(criterion.reason)
            )
        lines.append(
            "| "
            + " | ".join(
                [
                    _table_text(criterion.id),
                    _table_text(criterion.label),
                    f"{criterion.weight * 100:.0f}%",
                    _STATUS_LABELS[criterion.status],
                    f"{criterion.points:.1f}",
                    f"{criterion.confidence:.0f}",
                    evidence,
                ]
            )
            + " |"
        )

    lines.extend(["", "## Strengths", ""])
    lines.extend(_render_notes(assessment.strengths))
    lines.extend(["", "## Gaps", ""])
    lines.extend(_render_notes(assessment.gaps))
    lines.extend(["", "## Unanswered objections", ""])
    if assessment.unanswered_objections:
        lines.extend(f"- {_md_text(item)}" for item in assessment.unanswered_objections)
    else:
        lines.append("None")

    lines.extend(["", "## Transcript", ""])
    for exchange in data.transcript:
        lines.extend([f"### Turn {exchange.turn}", ""])
        if exchange.client_text is not None:
            if exchange.escalation_level is not None:
                lines.extend([f"Client escalation level {exchange.escalation_level}", ""])
            lines.extend([f"**Client:** {_md_text(exchange.client_text)}", ""])
        if exchange.trainee_text is not None:
            lines.extend([f"**Trainee:** {_md_text(exchange.trainee_text)}", ""])

    return "\n".join(lines).rstrip() + "\n"


def _render_notes(notes: list[ReportNote]) -> list[str]:
    if not notes:
        return ["None"]
    rendered = []
    for note in notes:
        turns = ", ".join(map(str, note.evidence_turns)) or "none"
        rendered.append(f"- {_md_text(note.text)} (evidence turns: {turns})")
    return rendered


def _md_text(value: str) -> str:
    escaped = escape(value, quote=False)
    escaped = re.sub(r"([\\`*_{}\[\]()!|])", r"\\\1", escaped)
    return escaped.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")


def _table_text(value: str) -> str:
    return " ".join(_md_text(value).replace("<br>", " ").split())


def render_html(markdown_text: str) -> tuple[str, str]:
    """Convert Markdown to sanitized HTML and return the full document and its body."""
    generated = markdown(markdown_text, extensions=["tables", "sane_lists"])
    generated = _apply_score_table_layout(generated)
    body = bleach.clean(
        generated,
        tags=_HTML_TAGS,
        attributes=_HTML_ATTRIBUTES,
        protocols=_HTML_PROTOCOLS,
        strip=True,
        strip_comments=True,
    )
    document = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Stakeholder Roleplay Assessment</title>
  <style>
    body {{
      color: #222;
      font: 14px/1.5 Arial, sans-serif;
      margin: 2rem auto;
      max-width: 1000px;
      padding: 0 1.5rem;
    }}
    h1, h2, h3 {{ color: #202a44; }}
    table {{ border-collapse: collapse; margin: 1rem 0; width: 100%; }}
    th, td {{
      border: 1px solid #e6e6e6;
      padding: .6rem .65rem;
      vertical-align: top;
    }}
    th {{ background: #f5f5f5; }}
    blockquote {{ border-left: 3px solid #c8c8c8; margin-left: 0; padding-left: 1rem; }}
    @media print {{ body {{ margin: 0; max-width: none; }} }}
  </style>
</head>
<body>
<main>{body}</main>
</body>
</html>
"""
    return document, body


def _apply_score_table_layout(generated: str) -> str:
    widths = (5, 24, 10, 10, 9, 14, 28)
    header_alignments = ("center",) * len(widths)
    cell_alignments = ("center", "left", "center", "center", "center", "center", "left")
    table_match = re.search(r"<table>.*?</table>", generated, flags=re.DOTALL)
    if table_match is None:
        return generated

    row_index = 0

    def layout_row(row_match: re.Match[str]) -> str:
        nonlocal row_index
        column_index = 0

        def layout_cell(cell_match: re.Match[str]) -> str:
            nonlocal column_index
            index = column_index
            column_index += 1
            if index >= len(widths):
                return cell_match.group()
            alignment = header_alignments if row_index == 0 else cell_alignments
            attributes = [f'align="{alignment[index]}"']
            if row_index == 0:
                attributes.append(f'width="{widths[index]}%"')
            return f"<{cell_match.group(1)} {' '.join(attributes)}>"

        row = re.sub(r"<(th|td)(?:\s+[^>]*)?>", layout_cell, row_match.group())
        row_index += 1
        return row

    table = re.sub(r"<tr>.*?</tr>", layout_row, table_match.group(), flags=re.DOTALL)
    return generated[: table_match.start()] + table + generated[table_match.end() :]


def _find_font_files() -> dict[str, Path]:
    windows_fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    candidates = [
        {
            "": windows_fonts / "arial.ttf",
            "B": windows_fonts / "arialbd.ttf",
            "I": windows_fonts / "ariali.ttf",
            "BI": windows_fonts / "arialbi.ttf",
        },
        {
            "": Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            "B": Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
            "I": Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf"),
            "BI": Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-BoldOblique.ttf"),
        },
        {
            "": Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"),
            "B": Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"),
            "I": Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Italic.ttf"),
            "BI": Path("/usr/share/fonts/truetype/liberation2/LiberationSans-BoldItalic.ttf"),
        },
    ]
    for family in candidates:
        if family[""].is_file():
            return {style: path for style, path in family.items() if path.is_file()}
    raise RuntimeError(
        "PDF generation requires an installed Arial, DejaVu Sans, or Liberation Sans TTF font"
    )


def render_pdf(html_body: str) -> bytes:
    """Render sanitized HTML to a Unicode-capable PDF."""
    font_files = _find_font_files()
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=16)
    pdf.set_margins(16, 16, 16)
    pdf.set_title("Stakeholder Roleplay Assessment")
    pdf.add_font("ReportSans", fname=str(font_files[""]))

    for style in ("B", "I", "BI"):
        pdf.add_font(
            "ReportSans",
            style=style,
            fname=str(font_files.get(style, font_files[""])),
        )

    pdf.add_page()
    pdf.set_font("ReportSans", size=10)
    pdf.write_html(html_body)
    return bytes(pdf.output())


def generate_report(
    db: Session, session_id: UUID, assessment: ValidatedAssessment
) -> ReportArtifacts:
    """Load a completed session and produce Markdown, sanitized HTML, and PDF bytes."""
    data = load_report_data(db, session_id, assessment)
    markdown_text = render_markdown(data)
    html_document, html_body = render_html(markdown_text)
    pdf = render_pdf(html_body)
    return ReportArtifacts(markdown=markdown_text, html=html_document, pdf=pdf)
