"""Morning: the admin sets the stage. Four things, in the order of the story."""

import json

import streamlit as st

from ui import state
from ui.client import ApiError
from ui.persona_form import default_persona, default_scenarios_json
from ui.widgets import (
    attempt,
    flash,
    live,
    persona_editor,
    show_extracted,
    show_flash,
    status_label,
)

client = state.client()

st.header("Set the stage")
st.caption(
    "Before anyone can chat: write the character card, publish it, load the situations, "
    "and upload the demand document."
)
show_flash()

card_tab, situations_tab, demand_tab = st.tabs(
    ["1 · Character card (write and publish)", "2 · Situations", "3 · Demand document"]
)


# --- 1 and 2: the character card --------------------------------------------------------------


def _version_picker(key: str, versions: list[dict]) -> int:
    numbers = [v["version_no"] for v in versions]
    status_of = {v["version_no"]: v["status"] for v in versions}
    return st.selectbox(
        "Version",
        numbers,
        index=len(numbers) - 1,
        format_func=lambda n: f"v{n} · {status_of[n]}",
        key=f"version-{key}",
    )


def _one_card(item: dict) -> None:
    key = item["key"]
    number = _version_picker(key, item["versions"])
    row = attempt(client.get_version, "persona", key, number)
    if row is None:
        return
    st.markdown(f"**{status_label(row['status'])}**")
    form_key = f"edit-{key}-{number}"

    if row["status"] == "draft":
        st.caption("A draft can still change. Only a published version can be used in chats.")
        with st.form(form_key):
            config = persona_editor(row["config"], form_key)
            save = st.form_submit_button("Save the draft")
        if save and attempt(client.edit_persona_draft, key, number, config) is not None:
            st.success("Draft saved.")
        if st.button("Publish this version", type="primary", key=f"publish-{form_key}"):
            if attempt(client.publish_persona, key, number) is not None:
                flash(f"{key} v{number} is published. Chats can use it now.")
                st.rerun()
    else:
        st.json(row["config"], expanded=False)
        st.caption(
            "A published version never changes. Later changes become a new version; "
            "chats already started keep the version they began with."
        )

    if st.button("Start a new version from the latest", key=f"new-{key}"):
        created = attempt(client.new_persona_version, key)
        if created is not None:
            flash(f"{key} v{created['version_no']} is a new draft, copied from the latest.")
            st.rerun()


with card_tab:
    keys = attempt(client.list_keys, "persona")
    if keys is not None and not keys:
        st.info("No character card yet. Create the first one below.")
    for item in keys or []:
        latest = item["versions"][-1]
        title = f"{item['key']} · latest v{latest['version_no']} ({latest['status']})"
        with st.expander(title, expanded=len(keys) == 1):
            _one_card(item)

    st.subheader("New character card")
    with st.form("new-card"):
        new_key = st.text_input("Key (lowercase letters, digits and dashes)", "verma-strict")
        new_config = persona_editor(default_persona(), "new")
        create = st.form_submit_button("Save as version 1 (draft)")
    if create:
        created = attempt(client.create_persona, new_key.strip(), new_config)
        if created is not None:
            flash(f"{created['key']} v1 saved as a draft. Open it above to publish.")
            st.rerun()


# --- the situations ---------------------------------------------------------------------------

with situations_tab:
    st.caption(
        "Loaded once, in one batch. The AI client chooses among them on its own; "
        "nobody picks one per chat. Loading the same file again changes nothing."
    )
    uploaded = st.file_uploader("A scenarios file (.json)", type=["json"], key="scenario-file")
    text = st.text_area(
        "Or paste the JSON here",
        default_scenarios_json() if uploaded is None else uploaded.getvalue().decode("utf-8"),
        height=260,
        key=f"scenario-text-{uploaded.name if uploaded else 'sample'}",
    )
    if st.button("Load the situations", type="primary"):
        try:
            payload = json.loads(text)
        except ValueError as exc:
            st.error(f"That is not valid JSON: {exc}")
        else:
            result = attempt(client.import_scenarios, payload)
            if result is not None:
                st.success(
                    f"{len(result['created'])} new, {len(result['updated'])} updated, "
                    f"{len(result['unchanged'])} unchanged."
                )

    st.subheader("Loaded situations")
    scenario_keys = attempt(client.list_keys, "scenario")
    if scenario_keys is not None and not scenario_keys:
        st.info("None yet. Chats cannot start until situations are loaded.")
    rows = []
    for item in scenario_keys or []:
        latest = item["versions"][-1]
        row = attempt(client.get_version, "scenario", item["key"], latest["version_no"])
        if row is not None:
            rows.append(
                {
                    "key": item["key"],
                    "version": latest["version_no"],
                    "status": latest["status"],
                    "title": row["config"].get("title", ""),
                    "situation": row["config"].get("situation", ""),
                }
            )
    if rows:
        st.dataframe(rows, hide_index=True, use_container_width=True)


# --- the demand document ----------------------------------------------------------------------


def _render_demand(row: dict) -> None:
    st.markdown(f"**{status_label(row['status'])}**")
    if row.get("error"):
        st.error(row["error"])
    if row["status"] == "ready":
        show_extracted(row.get("content"))
    if row["status"] != "extracting" and st.button("Delete", key=f"del-demand-{row['id']}"):
        try:
            client.delete_demand(row["id"])
        except ApiError as exc:  # for example: a chat already uses it
            st.error(exc.detail)
        else:
            flash("Deleted.")
            st.rerun()


with demand_tab:
    st.caption(
        "The Gama team's description of the project: what is being built and what they expect "
        "from a person. Everyone's chats use the newest one that is ready."
    )
    demand_file = st.file_uploader(
        "Demand document", type=["pdf", "docx", "txt"], key="demand-file"
    )
    if st.button("Upload the demand document", type="primary", disabled=demand_file is None):
        result = attempt(client.upload_demand, demand_file.name, demand_file.getvalue())
        if result is not None:
            flash(
                "That file is already there: showing the earlier record."
                if result.reused
                else "Uploaded. The reader is working on it.",
                "info" if result.reused else "success",
            )
            st.rerun()

    st.subheader("Uploaded documents")
    demands = attempt(client.list_demands)
    if demands is not None and not demands:
        st.info("None yet. Chats cannot start until a demand document is ready.")
    ready = [d for d in demands or [] if d["status"] == "ready"]
    in_use = max(ready, key=lambda d: d["created_at"])["id"] if ready else None
    for demand in demands or []:
        label = (
            f"{status_label(demand['status'])} · {demand['filename']} · "
            f"{demand['created_at'][:16]} · by {demand['uploaded_by']}"
            + ("  ·  IN USE" if demand["id"] == in_use else "")
        )
        with st.expander(label, expanded=demand["status"] != "ready"):
            live(lambda did=demand["id"]: client.get_demand(did), _render_demand)
