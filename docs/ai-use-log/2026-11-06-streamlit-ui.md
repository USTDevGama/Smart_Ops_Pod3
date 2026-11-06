# 2026-11-06 - a Streamlit UI that follows the story of one chat

- **Tool:** Claude Code (running inside VS Code).
- **Account:** TODO - the committer fills in the work account used.
- **What was shared:** our own design plan (the story of one chat, the API contract) and this repository's code. No seed-pack content, no secrets, no keys, no real trainee data. All demo data is made-up (`samples/`).
- **What came back:** the `ui/` folder (API client, chat rules, admin and trainee pages), `tests/ui/`, a localhost-only Streamlit config, a `ui` dependency group, a `make ui` shortcut and README notes.
- **Review:** TODO - the committer and a teammate confirm they have read and can explain every file before relying on it.
- **Known gaps to check by a person:** the pages were exercised headlessly (Streamlit's `AppTest`) and through the real API, but nobody has looked at them in a browser yet, so layout and wording need a human eye; the live status refresh while a file is being read runs in a Streamlit fragment and has only been tested with files that were already read; the dev login has no password.
