"""Anna starts the chat and talks to Ms. Verma."""

import streamlit as st

from ui import state
from ui.chat import ChatController, end_reason_text
from ui.widgets import attempt, flash, render_transcript, report_panel, show_flash

MAX_LEVEL = 4  # the character card's ladder has at most four steps

client = state.client()
st.header("Chat with the client")
show_flash()


def _start() -> None:
    st.caption(
        "Pick the client and your resume. The client speaks first. "
        "A chat needs a published client, a ready demand document, loaded situations "
        "and a ready resume of yours; the app tells you which one is missing."
    )
    personas = attempt(client.list_personas)
    profiles = attempt(client.list_profiles)
    if personas is None or profiles is None:
        return
    ready = [p for p in profiles if p["status"] == "ready"]
    if not personas:
        st.warning("No client is published yet. An admin has to publish a character card first.")
    if not ready:
        st.warning("You have no ready resume yet. Upload one on the 'My resume' page.")

    if personas and ready:
        persona = st.selectbox(
            "Client",
            personas,
            format_func=lambda p: f"{p['title']} (v{p['version_no']}): {p['summary']}",
        )
        profile = st.selectbox(
            "Resume", ready, format_func=lambda p: f"{p['filename']} · {p['created_at'][:16]}"
        )
        if st.button("Start the chat", type="primary"):
            session = attempt(client.start_session, persona["key"], profile["id"])
            if session is not None:
                st.session_state["chat"] = ChatController(client, session)
                st.rerun()

    st.subheader("Your earlier chats")
    sessions = attempt(client.list_sessions)
    if sessions:
        choice = st.selectbox(
            "Open a chat",
            sessions,
            format_func=lambda s: (
                f"{s['started_at'][:16]} · {s['persona']['key']} · {s['status']} · "
                f"{s['turns_used']} of {s['max_turns']} messages"
            ),
        )
        if st.button("Open"):
            detail = attempt(client.get_session, choice["id"])
            if detail is not None:
                st.session_state["chat"] = ChatController(client, detail)
                st.rerun()
    elif sessions is not None:
        st.caption("None yet.")


def _room(chat: ChatController) -> None:
    persona = chat.session["persona"]
    top, mood, used = st.columns([3, 2, 2])
    top.markdown(f"**{persona['key']}** (v{persona['version_no']})")
    mood.metric("Client mood", f"Level {chat.level} of {MAX_LEVEL}")
    used.metric("Your messages", f"{chat.turns_used} of {chat.max_turns}")
    st.progress(min(chat.level / MAX_LEVEL, 1.0))

    render_transcript(chat.turns)

    if chat.pending is not None:
        with st.chat_message("user"):
            st.write(chat.pending.content)
        st.warning(
            "That message did not go through, and nothing was saved. "
            "Sending it again is safe: it uses the same ticket, so it can never count twice."
        )
        again, drop = st.columns(2)
        if again.button("Send it again", type="primary"):
            _handle(chat, chat.retry())
        if drop.button("Discard it"):
            chat.discard_pending()
            st.rerun()
        return

    if chat.ended:
        st.info(f"This chat has ended. {end_reason_text(chat.end_reason)}")
        # However it ended (the message limit, End the chat, or an admin), the report is made.
        report_panel(client, chat.id)
        if st.button("Back to the start"):
            st.session_state.pop("chat")
            st.rerun()
        return

    text = st.chat_input("Your answer")
    if text:
        _handle(chat, chat.send(text))
    if st.button("End the chat"):
        attempt(chat.end)
        st.rerun()


def _handle(chat: ChatController, outcome) -> None:
    if outcome.ok:
        if outcome.ended:
            flash(end_reason_text(chat.end_reason), "info")
    elif not outcome.retryable:
        flash(outcome.error or "That message was refused.", "error")
    else:
        flash(f"Could not get a reply: {outcome.error}", "warning")
    st.rerun()


chat = st.session_state.get("chat")
if chat is None:
    _start()
else:
    _room(chat)
