"""Where the UI keeps the connection to the API between reruns."""

import streamlit as st

from ui.client import PodCClient


def connect(url: str, user: str, role: str) -> PodCClient:
    """The client for this login. A different login drops the open chat."""
    override = st.session_state.get("_client_override")  # tests put a ready-made client here
    if override is not None:
        st.session_state["_client"] = override
        return override
    client = st.session_state.get("_client")
    if client is None or client.identity != (url, user, role):
        client = PodCClient(url, user, role)
        st.session_state["_client"] = client
        st.session_state.pop("chat", None)
    return client


def client() -> PodCClient:
    return st.session_state["_client"]
