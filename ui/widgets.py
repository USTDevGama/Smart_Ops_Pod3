"""Small Streamlit pieces the pages share."""

from collections.abc import Callable

import pandas as pd
import streamlit as st

from ui.client import ApiError
from ui.persona_form import persona_config

ICONS = {
    "queued": "⏳",
    "extracting": "🔄",
    "ready": "✅",
    "failed": "❌",
    "draft": "✏️",
    "published": "✅",
    "retired": "📦",
    "active": "💬",
    "ended": "🏁",
}
STILL_WORKING = {"queued", "extracting"}  # the reader has not finished with the file yet


def status_label(status: str) -> str:
    return f"{ICONS.get(status, '•')} {status}"


def attempt(call: Callable, *args, **kwargs):
    """Call the API. If it fails, show why and return None."""
    try:
        return call(*args, **kwargs)
    except ApiError as exc:
        st.error(exc.detail)
        return None


# A message to show on the next run, for actions that end with a rerun.
def flash(message: str, kind: str = "success") -> None:
    st.session_state["_flash"] = (kind, message)


def show_flash() -> None:
    flashed = st.session_state.pop("_flash", None)
    if flashed:
        kind, message = flashed
        getattr(st, kind)(message)


def live(fetch: Callable[[], dict], render: Callable[[dict], None], interval: float = 2.0) -> None:
    """Show a record, and refresh it every few seconds while the reader is still working on it.

    When it finishes, the whole page reruns once so the refreshing stops.
    """
    first = fetch()
    working = first["status"] in STILL_WORKING

    @st.fragment(run_every=interval if working else None)
    def view() -> None:
        row = fetch() if working else first
        render(row)
        if working and row["status"] not in STILL_WORKING:
            st.rerun()

    view()


def show_extracted(content: dict | None) -> None:
    """The text the reader got out of the file: what the AI client will be given."""
    if not content or not content.get("text"):
        st.caption("Nothing was extracted.")
        return
    text = content["text"]
    with st.expander(f"Extracted text ({len(text):,} characters): what the AI client reads"):
        if st.checkbox("Show the raw markdown", key=f"raw-{hash(text)}"):
            st.code(text, language="markdown")
        else:
            st.markdown(text)


def render_transcript(turns: list[dict]) -> None:
    for turn in turns:
        if turn["role"] == "persona":
            with st.chat_message("assistant", avatar="🧑‍💼"):
                st.write(turn["content"])
                if turn.get("escalation_level"):
                    st.caption(f"Client mood: level {turn['escalation_level']}")
        else:
            with st.chat_message("user"):
                st.write(turn["content"])
                if turn.get("evaluation"):  # only admins receive these
                    with st.expander("Score notes (admin only)"):
                        st.json(turn["evaluation"])


def persona_editor(initial: dict, key: str) -> dict:
    """The character card as form fields. Returns the dict for the API, which validates it."""
    name = st.text_input("Name", initial.get("name", ""), key=f"{key}-name")
    role = st.text_input("Role", initial.get("role", ""), key=f"{key}-role")
    style = st.text_input("Style", initial.get("style", ""), key=f"{key}-style")
    concerns = st.text_area(
        "What she worries about (one per line)",
        "\n".join(initial.get("main_concerns", [])),
        key=f"{key}-concerns",
    )
    rules = st.text_area(
        "Rules she follows (one per line)", "\n".join(initial.get("rules", [])), key=f"{key}-rules"
    )

    st.markdown("**How she gets tougher** (step 1 is the mildest)")
    ladder = st.data_editor(
        pd.DataFrame(initial.get("escalation_ladder") or [{"step": 1, "move": ""}]),
        num_rows="dynamic",
        hide_index=True,
        key=f"{key}-ladder",
        column_config={
            "step": st.column_config.NumberColumn("Step", min_value=1, max_value=4, step=1),
            "move": st.column_config.TextColumn("What she does", width="large"),
        },
    )

    st.markdown("**The rules of the chat**")
    left, middle, right = st.columns(3)
    max_turns = left.number_input(
        "Messages from the trainee", 1, 50, int(initial.get("max_turns", 8)), key=f"{key}-max"
    )
    grace_turns = middle.number_input(
        "Bonus messages while answers improve",
        0,
        20,
        int(initial.get("grace_turns", 0)),
        key=f"{key}-grace",
    )
    min_turns = right.number_input(
        "Fewest messages", 1, 50, int(initial.get("min_turns", 3)), key=f"{key}-min"
    )
    t_escalate = st.slider(
        "A weaker answer than this makes her tougher",
        0.0,
        1.0,
        float(initial.get("t_escalate", 0.5)),
        0.05,
        key=f"{key}-esc",
    )
    t_deescalate = st.slider(
        "Two answers at least this good make her easier",
        0.0,
        1.0,
        float(initial.get("t_deescalate", 0.7)),
        0.05,
        key=f"{key}-deesc",
    )
    return persona_config(
        name=name,
        role=role,
        style=style,
        main_concerns=concerns,
        rules=rules,
        ladder=ladder.to_dict("records"),
        t_escalate=t_escalate,
        t_deescalate=t_deescalate,
        min_turns=min_turns,
        max_turns=max_turns,
        grace_turns=grace_turns,
        version=initial.get("version"),
    )
