# Samples

Made-up data of our own, for local work and tests. It follows the **shape** of the program's seed pack but contains none of its content. Never put real trainee or client data here, and never copy the confidential seed pack into this repo (the repo is public). Point `PODC_SEED_DIR` at the real pack kept elsewhere.

| File | Use |
|---|---|
| `proposals/billing_migration.txt` | a sample upload (the trainee profile once the team agrees the rename; today a short proposal text) |
| `personas/ms_verma_strict.json` | a persona (validated against `PersonaConfig`) |
| `scenarios/vendor_delay.json` | a scenario with objections and a good-answer checklist (validated against `ScenarioConfig`); the file shape is what `POST /admin/scenarios/import` takes |
| `demand/project_demand.json` | the project demand: what the project needs and the client expects (validated against `DemandConfig`) |
| `results/vendor_delay_result.json` | an example of the program's result format (validated against `RoleplayResult`) |
| `scoring/default.json` | a scoring profile (validated against `ScoringConfig`); not used by the API until scoring is built |

The three dimensions and all weights in `scoring/default.json` are **placeholders**, not from the BRD.

**TODO (Dev A):** add a PDF and a DOCX version of the proposal, plus one scanned page (an image of text) to exercise OCR.
