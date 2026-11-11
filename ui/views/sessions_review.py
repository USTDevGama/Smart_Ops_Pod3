"""Admins read the chats afterwards, including the score notes that trainees never see."""

import streamlit as st

from ui import state
from ui.chat import end_reason_text
from ui.widgets import attempt, render_transcript, report_panel, status_label

client = state.client()

st.header("Review chats")
st.caption("Every chat, in order. The score notes on each answer are visible to admins only.")

who, status = st.columns(2)
trainee = who.text_input("Only this trainee (name)", "").strip() or None
chosen = status.selectbox("Status", ["any", "active", "ended"])

sessions = attempt(client.list_sessions, None if chosen == "any" else chosen, trainee)
if sessions is not None and not sessions:
    st.info("No chats match.")

if sessions:
    st.dataframe(
        [
            {
                "started": s["started_at"][:16],
                "trainee": s["trainee_ref"],
                "client": f"{s['persona']['key']} v{s['persona']['version_no']}",
                "status": s["status"],
                "messages": f"{s['turns_used']} of {s['max_turns']}",
                "mood": s["level"],
                "ended because": end_reason_text(s["end_reason"]) if s["end_reason"] else "",
            }
            for s in sessions
        ],
        hide_index=True,
        width="stretch",
    )
    pick = st.selectbox(
        "Open a chat",
        sessions,
        format_func=lambda s: f"{s['started_at'][:16]} · {s['trainee_ref']} · {s['status']}",
    )
    detail = attempt(client.get_session, pick["id"])
    if detail is not None:
        st.subheader(f"{detail['trainee_ref']} with {detail['persona']['key']}")
        st.markdown(f"**{status_label(detail['status'])}**")
        render_transcript(detail["turns"])
        if detail["status"] == "ended":
            # Browsing must not start jobs: only the chat's own page asks for a report. A report
            # that is missing here can still be requested with "Generate it again".
            report_panel(client, detail["id"], ensure=False)
