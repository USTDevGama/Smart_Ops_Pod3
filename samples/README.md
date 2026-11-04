# Samples

Made-up data of our own, for local work and tests. It follows the **shape** of the program's seed pack but contains none of its content. Never put real trainee or client data here, and never copy the confidential seed pack into this repo (the repo is public). Point `PODC_SEED_DIR` at the real pack kept elsewhere.

| File | Use |
|---|---|
| `proposals/billing_migration.txt` | a short proposal with deliberate weak points (no budget breakdown, no risks, single vendor) |
| `proposals/billing_migration.docx` | the same proposal as a Word file (built by `scripts/make_samples.py`) |
| `proposals/billing_migration.pdf` | the same proposal as a PDF with a text layer (built by `scripts/make_samples.py`) |
| `proposals/billing_migration_with_figure.pdf` / `.docx` | a shortened proposal with a made-up budget bar chart and its caption, to exercise figure handling |
| `proposals/billing_migration_scanned.pdf` | the first page as an image with no text layer, to exercise OCR (needs the `tesseract` binary) |
| `personas/ms_verma_strict.json` | a persona (validated against `PersonaConfig`) |
| `scenarios/vendor_delay.json` | a scenario with objections and a good-answer checklist (validated against `ScenarioConfig`) |
| `results/vendor_delay_result.json` | an example of the program's result format (validated against `RoleplayResult`) |
| `scoring/default.json` | a scoring profile (validated against `ScoringConfig`) |

The three dimensions and all weights in `scoring/default.json` are **placeholders**, not from the BRD.

Regenerate the proposal files with `uv run python -m scripts.make_samples`.
