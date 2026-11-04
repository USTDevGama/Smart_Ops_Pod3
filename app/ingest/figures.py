"""Turns a figure (chart, diagram, picture) into text the persona can be given.

What a figure yields, in order of how far it can be trusted:
- the caption, which is text the trainee wrote;
- text read inside the picture (labels, numbers) by OCR: literal, but often incomplete;
- a label from Docling's picture classifier (bar chart, flow chart...);
- optionally a description written by a small vision model. It is often wrong (on a test chart
  it invented a value), so it is off by default and always marked as unverified.
"""

import re

# Below this the classifier is guessing, so no label is given.
LABEL_MIN_CONFIDENCE = 0.5

_CAPTION_START = re.compile(r"^\s*(figure|fig\.?)\s*\d+", re.IGNORECASE)


def looks_like_caption(text: str) -> bool:
    """A paragraph that starts "Figure 1" or "Fig. 2". Word does not link these to the picture."""
    return bool(_CAPTION_START.match(text))


def figure_label(item) -> str | None:
    """The classifier's best guess for the figure type, e.g. "bar chart", if it is confident."""
    classification = getattr(item.meta, "classification", None) if item.meta else None
    if classification is None or not classification.predictions:
        return None
    best = max(classification.predictions, key=lambda p: p.confidence)
    if best.confidence < LABEL_MIN_CONFIDENCE:
        return None
    return best.class_name.replace("_", " ")


def figure_description(item) -> str | None:
    """The vision model's description, if description was switched on."""
    description = getattr(item.meta, "description", None) if item.meta else None
    text = (description.text if description else "").strip()
    return text or None


def figure_text(
    label: str | None,
    caption: str,
    inner_text: list[str],
    description: str | None,
) -> str | None:
    """The text stored for one figure, or None when nothing at all is known about it."""
    if not (label or caption or inner_text or description):
        return None
    lines = [f"[Figure, {label}]" if label else "[Figure]"]
    if caption:
        lines.append(f"Caption: {caption}")
    if inner_text:
        lines.append(
            "Text read inside the figure (by OCR, may be incomplete): " + " | ".join(inner_text)
        )
    if description:
        lines.append(f"Machine-generated description (unverified, may be wrong): {description}")
    if not (caption or inner_text or description):
        lines.append("No text could be read from this figure.")
    return "\n".join(lines)
