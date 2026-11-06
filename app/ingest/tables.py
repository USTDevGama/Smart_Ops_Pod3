"""Turns table rows into markdown text, the same way for PDF and DOCX tables."""


def table_markdown(rows: list[list[str | None]]) -> str | None:
    """A markdown table from rows of cells (the first row is the header), or None if empty."""
    cleaned = [
        [(cell or "").replace("\n", " ").replace("|", "\\|").strip() for cell in row]
        for row in rows
        if row
    ]
    cleaned = [row for row in cleaned if any(row)]
    if not cleaned:
        return None
    width = max(len(row) for row in cleaned)
    cleaned = [row + [""] * (width - len(row)) for row in cleaned]
    header, *body = cleaned
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(row) + " |" for row in body]
    return "\n".join(lines)
