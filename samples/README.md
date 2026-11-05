# Samples

Made-up data of our own, for local work and tests. It follows the **shape** of the program's seed pack but contains none of its content. Never put real trainee or client data here, and never copy the confidential seed pack into this repo (the repo is public). Point `PODC_SEED_DIR` at the real pack kept elsewhere.

| File | Use |
|---|---|
| `profiles/sample_resume.txt` | a made-up trainee profile (resume) of one page, the kind of file a trainee uploads |
| `personas/ms_verma_strict.json` | a persona (validated against `PersonaConfig`) |
| `scenarios/vendor_delay.json` | a scenario with objections and a good-answer checklist (validated against `ScenarioConfig`); the file shape is what `POST /admin/scenarios/import` takes |
| `demand/project_demand.txt` | a made-up project demand document, the kind an admin uploads (what the project needs and the client expects) |
| `results/vendor_delay_result.json` | an example of the program's result format (validated against `RoleplayResult`) |
| `scoring/default.json` | a scoring profile (validated against `ScoringConfig`); not used by the API until scoring is built |

The three dimensions and all weights in `scoring/default.json` are **placeholders**, not from the BRD.

**TODO (Dev A):** add a PDF and a DOCX version of the profile, plus one scanned page (an image of text) to exercise OCR.
