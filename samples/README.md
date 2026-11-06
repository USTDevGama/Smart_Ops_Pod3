# Samples

Made-up data of our own, for local work and tests. It follows the **shape** of the program's seed pack but contains none of its content. Never put real trainee or client data here, and never copy the confidential seed pack into this repo (the repo is public). Point `PODC_SEED_DIR` at the real pack kept elsewhere.

| File | Use |
|---|---|
| `profiles/sample_resume.txt` | a made-up trainee profile (resume) of one page, the kind of file a trainee uploads |
| `personas/ms_verma_strict.json` | a persona (validated against `PersonaConfig`) |
| `scenarios/vendor_delay.json` | a scenario with objections and a good-answer checklist (validated against `ScenarioConfig`); the file shape is what `POST /admin/scenarios/import` takes |
| `demand/project_demand.txt` | a made-up project demand document uploaded by an admin |
| `results/llm_output.json` | raw criterion scores and evidence returned by the scoring LLM (`points` are JSON numbers) |
| `results/PodC_Sample_Report_v4.md` | the required final Markdown report format |
| `scoring/default.json` | a criterion rubric and provisional confidence settings (validated against `ScoringConfig`) |

`docs/scoring_output.schema.json` documents the scoring LLM response. The separate
`docs/roleplay_result.schema.json` documents the outgoing Pod D result contract.

The overall score is the weighted sum of criterion points multiplied by 100. Confidence weights,
status cutoffs and other confidence parameters in `scoring/default.json` are provisional and must
be calibrated against representative cases before production use.

**TODO (Dev A):** add a PDF and a DOCX version of the profile, plus one scanned page (an image of text) to exercise OCR.
