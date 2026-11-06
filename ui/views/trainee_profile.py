"""Anna arrives: she uploads her resume and watches it being read."""

import streamlit as st

from ui import state
from ui.client import ApiError
from ui.widgets import attempt, flash, live, show_extracted, show_flash, status_label

client = state.client()

st.header("My resume")
st.caption(
    "Upload a PDF, Word or text file (up to 10 MB). Only you and the admins can see it. "
    "The same file again gives you the same record back."
)
show_flash()

uploaded = st.file_uploader("Resume", type=["pdf", "docx", "txt"], key="resume-file")
if st.button("Upload", type="primary", disabled=uploaded is None):
    result = attempt(client.upload_profile, uploaded.name, uploaded.getvalue())
    if result is not None:
        flash(
            "You had already uploaded this file: showing the earlier record."
            if result.reused
            else "Uploaded. It is being read now.",
            "info" if result.reused else "success",
        )
        st.rerun()

st.subheader("Your uploads")
profiles = attempt(client.list_profiles)
if profiles is not None and not profiles:
    st.info("You have not uploaded a resume yet.")


def _render(row: dict) -> None:
    st.markdown(f"**{status_label(row['status'])}**")
    if row.get("error"):
        st.error(row["error"])
    if row["status"] == "ready":
        show_extracted(row.get("content"))
        st.caption("This resume can now be used to start a chat.")
    if row["status"] != "extracting":
        if st.button("Delete", key=f"del-{row['id']}"):
            try:
                client.delete_profile(row["id"])
            except ApiError as exc:  # the API says why, e.g. a chat already uses it
                st.error(exc.detail)
            else:
                flash("Deleted.")
                st.rerun()


for profile in profiles or []:
    title = (
        f"{status_label(profile['status'])} · {profile['filename']} · {profile['created_at'][:16]}"
    )
    with st.expander(title, expanded=profile["status"] != "ready"):
        live(lambda pid=profile["id"]: client.get_profile(pid), _render)
