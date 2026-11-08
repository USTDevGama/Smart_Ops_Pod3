# Samples

Made-up data of our own, for local work and tests. It follows the **shape** of the program's seed pack but contains none of its content. Never put real trainee or client data here, and never copy the confidential seed pack into this repo (the repo is public). Point `PODC_SEED_DIR` at the real pack kept elsewhere.

| File | Use |
|---|---|
| `profiles/sample_resume.txt` | a made-up trainee profile (resume) of one page, the kind of file a trainee uploads |
| `profiles/sample_resume.docx`, `.pdf` | the same profile as a Word file and as a PDF with a text layer (built by `scripts/make_samples.py`) |
| `personas/ms_verma_strict.json` | a persona (validated against `PersonaConfig`) |
| `scenarios/vendor_delay.json` | a scenario with objections and a good-answer checklist (validated against `ScenarioConfig`); the file shape is what `POST /admin/scenarios/import` takes |
| `demand/project_demand.txt` | a made-up project demand document uploaded by an admin |
| `demand/project_demand.docx`, `.pdf` | the same demand document as Word and text-layer PDF files (built by `scripts/make_samples.py`) |
| `Sample_Proposal_Store_Inventory_Dashboard.docx` | a fictional long document used as a DOCX extraction test fixture; it is not an additional configurable session input |
| `results/llm_output.json` | example final criterion scores and evidence in the expected conversation-agent output shape (`points` are JSON numbers) |
| `results/PodC_Sample_Report_v4.md` | the required final Markdown report format |
| `scoring/default.json` | a criterion rubric and provisional confidence settings (validated against `ScoringConfig`) |

`docs/scoring_output.schema.json` documents the final criterion-level output expected from the
conversation-agent component. The separate `docs/roleplay_result.schema.json` documents the
outgoing Pod D result contract.

The overall score is the weighted sum of criterion points multiplied by 100. Confidence weights,
status cutoffs and other confidence parameters in `scoring/default.json` are provisional and must
be calibrated against representative cases before production use.

Regenerate the DOCX and PDF versions with `uv run python -m scripts.make_samples`. There is no scanned sample: ingestion does no OCR, and a scanned PDF is refused with a clear message (tested with an image built in the test).
