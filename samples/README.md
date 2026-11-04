# Samples

Made-up data of our own, for local work and tests. It follows the **shape** of the program's seed pack but contains none of its content. Never put real trainee or client data here, and never copy the confidential seed pack into this repo (the repo is public). Point `PODC_SEED_DIR` at the real pack kept elsewhere.

| File | Use |
|---|---|
| `proposals/billing_migration.txt` | a short proposal with deliberate weak points (no budget breakdown, no risks, single vendor) |
| `personas/ms_verma_strict.json` | a persona (validated against `PersonaConfig`) |
| `scenarios/vendor_delay.json` | a scenario with objections and a good-answer checklist (validated against `ScenarioConfig`) |
| `results/llm_output.json` | raw criterion scores and evidence returned by the scoring LLM |
| `results/PodC_Sample_Report_v4.md` | the required final Markdown report format |
| `scoring/default.json` | a criterion rubric and provisional confidence settings (validated against `ScoringConfig`) |

The overall score is the weighted sum of criterion points multiplied by 100. Confidence weights,
status cutoffs and other confidence parameters in `scoring/default.json` are provisional and must
be calibrated against representative cases before production use.

**TODO (Dev A):** add a PDF and a DOCX version of the proposal, plus one scanned page (an image of text) to exercise OCR.
