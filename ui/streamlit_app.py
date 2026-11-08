"""The Streamlit app: sign in (dev login), then the pages for that role.

Run: uv run --group ui streamlit run ui/streamlit_app.py
The API address comes from PODC_API_URL (default http://localhost:8000).
"""

import os
import sys
from pathlib import Path

# `streamlit run ui/streamlit_app.py` only puts this folder on the path, not the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st  # noqa: E402

from ui import state  # noqa: E402
from ui.client import DEFAULT_URL  # noqa: E402

st.set_page_config(page_title="Stakeholder roleplay", page_icon="💬", layout="wide")

with st.sidebar:
    st.title("Stakeholder roleplay")
    url = st.text_input("API address", os.environ.get("PODC_API_URL", DEFAULT_URL))
    user = st.text_input("Your name", st.session_state.get("user", "anna")).strip()
    role = st.selectbox("Role", ["trainee", "admin"])
    st.session_state["user"] = user
    st.caption("Dev login only: the name and role are sent as headers. Real login comes later.")

client = state.connect(url, user, role)

with st.sidebar:
    st.divider()
    if client.ready():
        try:
            st.caption(f"✅ API reachable · v{client.meta()['version']}")
        except Exception:
            st.caption("✅ API reachable")
    else:
        st.caption("❌ The API is not reachable. Start it with `make run`.")

trainee_pages = [
    st.Page("views/trainee_profile.py", title="My resume", icon="📄", default=role == "trainee"),
    st.Page("views/trainee_chat.py", title="Chat", icon="💬"),
]
admin_pages = [
    st.Page("views/admin_setup.py", title="Set the stage", icon="🛠️", default=role == "admin"),
    st.Page("views/sessions_review.py", title="Review chats", icon="🔎"),
]
pages = {"Admin": admin_pages, "Trainee": trainee_pages} if role == "admin" else trainee_pages
st.navigation(pages).run()
